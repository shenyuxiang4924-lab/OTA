/*
 * @Author: nikibikikii-star nikibikikii@gmail.com
 * @Date: 2026-07-06 14:26:59
 * @LastEditors: nikibikikii-star nikibikikii@gmail.com
 * @LastEditTime: 2026-07-06 14:30:59
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\OTA-main\at_test\Hardware\Esp32.c
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#include "Esp32.h"
#include "usart.h"
#include "gpio.h"
#include <string.h>

#define buffer_length 1024

#define pc_usart USART1
#define pc_huart huart1
#define esp32_usart USART2
#define esp32_huart huart2

static uint8_t esp32_rx_buffer[buffer_length];
static uint8_t pc_rx_buffer[buffer_length];

volatile static uint8_t pc_tx_flag = 0;
volatile static uint16_t pc_tx_len = 0;
volatile static uint8_t esp32_tx_flag = 0;
volatile static uint16_t esp32_tx_len = 0;

void Esp32_init(void)
{
    memset(esp32_rx_buffer, 0, buffer_length);
    memset(pc_rx_buffer, 0, buffer_length);
    HAL_UARTEx_ReceiveToIdle_IT(&esp32_huart, esp32_rx_buffer, buffer_length);
    HAL_UARTEx_ReceiveToIdle_IT(&pc_huart, pc_rx_buffer, buffer_length);
    HAL_GPIO_WritePin(GPIOC, GPIO_PIN_13, GPIO_PIN_SET);
    HAL_Delay(1000);
    HAL_GPIO_WritePin(GPIOC, GPIO_PIN_13, GPIO_PIN_RESET);
}

void Esp32_connect(void)
{
    if (pc_tx_flag)
    {
        if (strstr((char *)esp32_rx_buffer, "OK") != NULL)
        {
            HAL_GPIO_WritePin(GPIOC, GPIO_PIN_13, GPIO_PIN_RESET);
        }
        HAL_UART_Transmit(&pc_huart, esp32_rx_buffer, pc_tx_len, 1000);
        memset(esp32_rx_buffer, 0, buffer_length);
        pc_tx_flag = 0;
    }
    if (esp32_tx_flag)
    {
        if (strstr((char *)pc_rx_buffer, "AT") != NULL)
        {
            HAL_GPIO_WritePin(GPIOC, GPIO_PIN_13, GPIO_PIN_SET);
        }
        pc_rx_buffer[esp32_tx_len] = 0x0D;
        pc_rx_buffer[esp32_tx_len + 1] = 0x0A;
        esp32_tx_len += 2;
        HAL_UART_Transmit(&esp32_huart, pc_rx_buffer, esp32_tx_len, 1000);
        memset(pc_rx_buffer, 0, buffer_length);
        esp32_tx_flag = 0;
    }
    if (HAL_GPIO_ReadPin(GPIOC, GPIO_PIN_0))
    {
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);
    }
    else
    {
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
    }
}

void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    if (huart->Instance == pc_usart)
    {
        esp32_tx_flag = 1;
        esp32_tx_len = Size;
        HAL_UARTEx_ReceiveToIdle_IT(&pc_huart, pc_rx_buffer, buffer_length);
    }
    else if (huart->Instance == esp32_usart)
    {
        pc_tx_flag = 1;
        pc_tx_len = Size;
        HAL_UARTEx_ReceiveToIdle_IT(&esp32_huart, esp32_rx_buffer, buffer_length);
    }
}
