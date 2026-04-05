/**
 * woolf_reader firmware — ESP32-S3
 *
 * 功能：
 *   1. 读取双摇杆 ADC，发送光标/选中事件
 *   2. 读取摇杆按键，发送确认/取消事件
 *   3. I2S 麦克风 + WakeNet 检测唤醒词，发送 wake 事件
 *
 * 所有事件通过 USB CDC Serial 以 JSON 行发给电脑：
 *   {"event":"cursor","value":"up"}
 *   {"event":"cursor","value":"down"}
 *   {"event":"select","value":"expand"}
 *   {"event":"action","value":""}      ← 右摇杆按压（选中/确认）
 *   {"event":"cancel","value":""}      ← 左摇杆按压
 *   {"event":"wake","value":"woolf"}   ← 唤醒词检测到
 *
 * ── 接线说明 ──────────────────────────────────────────────
 *  右摇杆 Y 轴  → GPIO1  (ADC1_CH0)
 *  左摇杆 Y 轴  → GPIO4  (ADC1_CH3)
 *  右摇杆按键   → GPIO3  (内部上拉，低电平有效)
 *  左摇杆按键   → GPIO6  (内部上拉，低电平有效)
 *  麦克风 CLK   → GPIO7  (I2S BCLK)
 *  麦克风 WS    → GPIO8  (I2S LRCLK)
 *  麦克风 DATA  → GPIO9  (I2S DOUT → MCU DIN)
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

/* ── 引脚配置（按实际接线修改）────────────────────────── */
#define RIGHT_JOY_Y_CH    ADC_CHANNEL_0    // GPIO1
#define LEFT_JOY_Y_CH     ADC_CHANNEL_3    // GPIO4
#define RIGHT_BTN_PIN     GPIO_NUM_3
#define LEFT_BTN_PIN      GPIO_NUM_6

#define I2S_CLK_PIN       GPIO_NUM_7
#define I2S_WS_PIN        GPIO_NUM_8
#define I2S_DATA_PIN      GPIO_NUM_9

/* ── 摇杆参数 ─────────────────────────────────────────── */
#define JOY_CENTER        2048
#define JOY_DEADZONE      500
#define MOVE_INTERVAL_MS  150   // 持续拨动时重复发事件的最小间隔

/* ── 发送事件 ─────────────────────────────────────────── */
static void send_event(const char *event, const char *value) {
    printf("{\"event\":\"%s\",\"value\":\"%s\"}\n", event, value);
    fflush(stdout);
}

/* ════════════════════════════════════════════════════════
 * Task 1：摇杆 + 按键
 * ════════════════════════════════════════════════════════ */

static adc_oneshot_unit_handle_t s_adc;

static void init_adc(void) {
    adc_oneshot_unit_init_cfg_t unit_cfg = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &s_adc));

    adc_oneshot_chan_cfg_t ch_cfg = {
        .atten    = ADC_ATTEN_DB_12,   // 0~3.3V 量程
        .bitwidth = ADC_BITWIDTH_12,   // 0~4095
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, RIGHT_JOY_Y_CH, &ch_cfg));
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, LEFT_JOY_Y_CH,  &ch_cfg));
}

static void init_buttons(void) {
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << RIGHT_BTN_PIN) | (1ULL << LEFT_BTN_PIN),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
}

static void joystick_task(void *arg) {
    typedef enum { DIR_NONE, DIR_UP, DIR_DOWN } Dir;

    Dir  last_r_dir   = DIR_NONE;
    Dir  last_l_dir   = DIR_NONE;
    bool last_r_btn   = false;
    bool last_l_btn   = false;
    TickType_t last_move = 0;

    while (1) {
        int r_y, l_y;
        adc_oneshot_read(s_adc, RIGHT_JOY_Y_CH, &r_y);
        adc_oneshot_read(s_adc, LEFT_JOY_Y_CH,  &l_y);

        TickType_t now       = xTaskGetTickCount();
        bool       can_rep   = (now - last_move) > pdMS_TO_TICKS(MOVE_INTERVAL_MS);

        /* 右摇杆 Y → cursor up / down */
        Dir r_dir = DIR_NONE;
        if (r_y < JOY_CENTER - JOY_DEADZONE) r_dir = DIR_UP;
        if (r_y > JOY_CENTER + JOY_DEADZONE) r_dir = DIR_DOWN;

        if (r_dir != DIR_NONE && (r_dir != last_r_dir || can_rep)) {
            send_event("cursor", r_dir == DIR_UP ? "up" : "down");
            last_move = now;
        }
        last_r_dir = r_dir;

        /* 左摇杆 Y 下拉 → 扩展选中行数 */
        Dir l_dir = DIR_NONE;
        if (l_y > JOY_CENTER + JOY_DEADZONE) l_dir = DIR_DOWN;

        if (l_dir == DIR_DOWN && can_rep) {
            send_event("select", "expand");
            last_move = now;
        }
        last_l_dir = l_dir;

        /* 右摇杆按压（低电平有效）→ action（前端按状态解释为 select 或 confirm）*/
        bool r_btn = (gpio_get_level(RIGHT_BTN_PIN) == 0);
        if (r_btn && !last_r_btn) {
            send_event("action", "");
        }
        last_r_btn = r_btn;

        /* 左摇杆按压 → cancel */
        bool l_btn = (gpio_get_level(LEFT_BTN_PIN) == 0);
        if (l_btn && !last_l_btn) {
            send_event("cancel", "");
        }
        last_l_btn = l_btn;

        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

/* ════════════════════════════════════════════════════════
 * Task 2：I2S 麦克风 + WakeNet 唤醒词检测
 *
 * 唤醒词"伍尔夫"需要自定义模型：
 *   1. 到 https://github.com/espressif/esp-sr 查看 CustomVoice 说明
 *   2. 黑客松阶段可用内置"Hi Lexin"(嗨乐鑫)模型替代验证流程
 *   3. 用 idf.py menuconfig → ESP Speech Recognition → WakeNet model 选择
 * ════════════════════════════════════════════════════════ */

#define I2S_SAMPLE_RATE   16000
#define I2S_BUF_SAMPLES   512     // WakeNet 每次喂 512 个 16-bit 采样

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
    /* ── WakeNet 初始化 ─────────────────────────────────── */
    srmodel_list_t *models = esp_srmodel_filter(
        esp_srmodel_init("model"), ESP_WN_PREFIX, NULL
    );
    if (!models || models->num == 0) {
        ESP_LOGE(TAG, "No WakeNet model found. Flash a model via idf.py menuconfig.");
        vTaskDelete(NULL);
        return;
    }

    esp_wn_iface_t *wn       = &WAKENET_MODEL;
    model_iface_data_t *wnmd = wn->create(models->model_name[0], DET_MODE_90);
    int wn_chunk = wn->get_samp_chunksize(wnmd);  // 通常是 512

    /* ── 读取缓冲（32-bit I2S → 取高 16-bit）──────────── */
    int32_t  *raw  = malloc(wn_chunk * sizeof(int32_t));
    int16_t  *pcm  = malloc(wn_chunk * sizeof(int16_t));
    size_t    bytes_read;

    ESP_LOGI(TAG, "WakeNet ready. Say the wake word.");

    while (1) {
        i2s_channel_read(s_i2s_rx, raw, wn_chunk * sizeof(int32_t),
                         &bytes_read, portMAX_DELAY);

        /* INMP441 输出左对齐 32-bit，有效数据在高 16-bit */
        for (int i = 0; i < wn_chunk; i++) {
            pcm[i] = (int16_t)(raw[i] >> 16);
        }

        int wn_result = wn->detect(wnmd, pcm);
        if (wn_result > 0) {
            ESP_LOGI(TAG, "Wake word detected!");
            send_event("wake", "woolf");

            /* 防抖：检测到后静默 1.5 秒，避免连续触发 */
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
    init_buttons();
    init_i2s_mic();

    /* 摇杆任务：优先级低，20ms 轮询 */
    xTaskCreate(joystick_task, "joystick", 4096, NULL, 3, NULL);

    /* 麦克风任务：优先级高，实时音频处理 */
    xTaskCreate(mic_wake_task, "mic_wake", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "Tasks started. Serial output on USB CDC.");
}
