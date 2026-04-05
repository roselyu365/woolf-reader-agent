/**
 * woolf_reader firmware — ESP32-S3 (revised)
 *
 * 硬件：
 *   1. 单摇杆 Y 轴（弹性回中），检测上/下
 *   2. 两个霍尔传感器，检测圆筒左推/右拉状态（二态，无中位）
 *   3. I2S 麦克风 + WakeNet 检测唤醒词
 *
 * 所有事件通过 USB CDC Serial 以 JSON 行发给电脑：
 *   {"event":"cursor","value":"up"}      ← 摇杆上拨
 *   {"event":"cursor","value":"down"}    ← 摇杆下拨
 *   {"event":"select_start","value":""} ← 圆筒左→右（开始选择）
 *   {"event":"select_end","value":""}   ← 圆筒右→左（结束选择，前端决定确认/取消）
 *   {"event":"wake","value":"woolf"}    ← 唤醒词检测到
 *
 * ── 接线说明（XIAO ESP32S3，从左侧引脚第1脚起计数）─────
 *  第1脚 D0 GPIO2  → HALL1 霍尔传感器（右拉触发，ADC1_CH1）
 *  第3脚 D2 GPIO4  → 摇杆 Y 轴（上拨≈0-1000mv，中位≈1500-2000mv，下拨≈2500mv+，ADC1_CH3）
 *  第5脚 D4 GPIO6  → HALL2 霍尔传感器（左拉触发，ADC1_CH5）
 *  麦克风 CLK      → GPIO7  (I2S BCLK)
 *  麦克风 WS       → GPIO8  (I2S LRCLK)
 *  麦克风 DATA     → GPIO9  (I2S DOUT → MCU DIN)
 * ──────────────────────────────────────────────────────────
 */

#include <stdio.h>
#include <string.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "driver/i2s_std.h"
#include "esp_log.h"

/* ESP-SR WakeNet */
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "model_path.h"

static const char *TAG = "woolf";

/* ── 引脚配置 ──────────────────────────────────────────── */
#define HALL_R_CH         ADC_CHANNEL_1    // GPIO2  HALL1 霍尔传感器（右拉触发）
#define JOY_Y_CH          ADC_CHANNEL_3    // GPIO4  摇杆 Y 轴
#define HALL_L_CH         ADC_CHANNEL_5    // GPIO6  HALL2 霍尔传感器（左拉触发）

#define I2S_CLK_PIN       GPIO_NUM_7
#define I2S_WS_PIN        GPIO_NUM_8
#define I2S_DATA_PIN      GPIO_NUM_9

/* ── 摇杆阈值（ADC 12-bit，量程约 0-3100mv）─────────────
 * 上拨 < 1300，死区 1300~3200，下拨 > 3200
 * 若实测偏差较大，按比例调整：ADC值 ≈ 电压mv * 4095 / 3100
 * ───────────────────────────────────────────────────── */
#define JOY_UP_THRESH     1300
#define JOY_DOWN_THRESH   3200
#define MOVE_INTERVAL_MS  150   // 持续拨动时重复发事件的最小间隔

/* ── 霍尔传感器阈值 ─────────────────────────────────────
 * 磁铁靠近时电压低，低于此阈值判定为"该侧触发"
 * TODO: 上电后实测两个传感器在各自触发/非触发状态的电压，按需调整
 * ───────────────────────────────────────────────────── */
#define HALL_CLOSE_THRESH 1800

/* ── 发送事件 ─────────────────────────────────────────── */
static void send_event(const char *event, const char *value) {
    printf("{\"event\":\"%s\",\"value\":\"%s\"}\n", event, value);
    fflush(stdout);
}

/* ════════════════════════════════════════════════════════
 * Task 1：摇杆 + 霍尔传感器（圆筒状态检测）
 * ════════════════════════════════════════════════════════ */

static adc_oneshot_unit_handle_t s_adc;

static void init_adc(void) {
    adc_oneshot_unit_init_cfg_t unit_cfg = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &s_adc));

    adc_oneshot_chan_cfg_t ch_cfg = {
        .atten    = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, HALL_R_CH,  &ch_cfg));
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, JOY_Y_CH,   &ch_cfg));
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, HALL_L_CH,  &ch_cfg));
}

typedef enum { CYL_RIGHT, CYL_LEFT } CylState;

static void input_task(void *arg) {
    typedef enum { DIR_NONE, DIR_UP, DIR_DOWN } JoyDir;

    JoyDir   last_joy_dir = DIR_NONE;
    CylState cyl_state    = CYL_LEFT;   // 初始状态：左推（默认阅读态）
    TickType_t last_move  = 0;

    /* 上电时读一次霍尔传感器，确定初始圆筒状态 */
    {
        int hr, hl;
        adc_oneshot_read(s_adc, HALL_R_CH, &hr);
        adc_oneshot_read(s_adc, HALL_L_CH, &hl);
        if (hr < HALL_CLOSE_THRESH && hl >= HALL_CLOSE_THRESH) {
            cyl_state = CYL_RIGHT;
        }
    }

    while (1) {
        int joy_y, hall_r, hall_l;
        adc_oneshot_read(s_adc, JOY_Y_CH,  &joy_y);
        adc_oneshot_read(s_adc, HALL_R_CH, &hall_r);
        adc_oneshot_read(s_adc, HALL_L_CH, &hall_l);

        TickType_t now    = xTaskGetTickCount();
        bool       can_rep = (now - last_move) > pdMS_TO_TICKS(MOVE_INTERVAL_MS);

        /* ── 摇杆 ────────────────────────────────────── */
        JoyDir joy_dir = DIR_NONE;
        if (joy_y < JOY_UP_THRESH)   joy_dir = DIR_UP;
        if (joy_y > JOY_DOWN_THRESH) joy_dir = DIR_DOWN;

        if (joy_dir != DIR_NONE && (joy_dir != last_joy_dir || can_rep)) {
            send_event("cursor", joy_dir == DIR_UP ? "up" : "down");
            last_move = now;
        }
        last_joy_dir = joy_dir;

        /* ── 圆筒状态检测（霍尔传感器）────────────────
         * 判定规则：哪侧霍尔电压低 → 磁铁在哪侧 → 圆筒在哪侧
         * 两侧都低/都高属于过渡态，保持上一个已知状态
         * ─────────────────────────────────────────── */
        bool r_close = (hall_r < HALL_CLOSE_THRESH);
        bool l_close = (hall_l < HALL_CLOSE_THRESH);

        CylState new_cyl = cyl_state;
        if (r_close && !l_close) new_cyl = CYL_RIGHT;
        if (l_close && !r_close) new_cyl = CYL_LEFT;

        if (new_cyl != cyl_state) {
            if (new_cyl == CYL_RIGHT) {
                send_event("select_start", "");
            } else {
                send_event("select_end", "");
            }
            cyl_state = new_cyl;
        }

        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

/* ════════════════════════════════════════════════════════
 * Task 2：I2S 麦克风 + WakeNet 唤醒词检测
 * ════════════════════════════════════════════════════════ */

#define I2S_SAMPLE_RATE   16000
#define I2S_BUF_SAMPLES   512

static i2s_chan_handle_t s_i2s_rx;

static void init_i2s_mic(void) {
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(
        I2S_NUM_0, I2S_ROLE_MASTER
    );
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &s_i2s_rx));

    i2s_std_config_t std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(I2S_SAMPLE_RATE),
        .slot_cfg = I2S_STD_MSB_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO
        ),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_CLK_PIN,
            .ws   = I2S_WS_PIN,
            .dout = I2S_GPIO_UNUSED,
            .din  = I2S_DATA_PIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_i2s_rx, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_i2s_rx));
}

static void mic_wake_task(void *arg) {
    srmodel_list_t *models = esp_srmodel_filter(
        esp_srmodel_init("model"), ESP_WN_PREFIX, NULL
    );
    if (!models || models->num == 0) {
        ESP_LOGE(TAG, "No WakeNet model found.");
        vTaskDelete(NULL);
        return;
    }

    esp_wn_iface_t     *wn   = &WAKENET_MODEL;
    model_iface_data_t *wnmd = wn->create(models->model_name[0], DET_MODE_90);
    int wn_chunk = wn->get_samp_chunksize(wnmd);

    int32_t *raw = malloc(wn_chunk * sizeof(int32_t));
    int16_t *pcm = malloc(wn_chunk * sizeof(int16_t));
    size_t   bytes_read;

    ESP_LOGI(TAG, "WakeNet ready.");

    while (1) {
        i2s_channel_read(s_i2s_rx, raw, wn_chunk * sizeof(int32_t),
                         &bytes_read, portMAX_DELAY);
        for (int i = 0; i < wn_chunk; i++) {
            pcm[i] = (int16_t)(raw[i] >> 16);
        }
        if (wn->detect(wnmd, pcm) > 0) {
            ESP_LOGI(TAG, "Wake word detected!");
            send_event("wake", "woolf");
            vTaskDelay(pdMS_TO_TICKS(1500));
        }
    }

    free(raw);
    free(pcm);
}

/* ════════════════════════════════════════════════════════
 * app_main
 * ════════════════════════════════════════════════════════ */

void app_main(void) {
    ESP_LOGI(TAG, "Woolf Reader firmware starting...");

    init_adc();
    init_i2s_mic();

    xTaskCreate(input_task,    "input",    4096, NULL, 3, NULL);
    xTaskCreate(mic_wake_task, "mic_wake", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "Tasks started.");
}
