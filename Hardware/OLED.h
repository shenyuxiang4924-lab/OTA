/*
 * @Author: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @Date: 2026-04-10 10:36:01
 * @LastEditors: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @LastEditTime: 2026-04-12 14:35:46
 * @FilePath: \MDK-ARM\OLED.h
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#ifndef __OLED_H
#define __OLED_H

#include <stdint.h>
void OLED_Init(void);
void OLED_Clear(void);
void OLED_Map(void);
void OLED_DrawChar(uint8_t x, uint8_t y, uint8_t chr);
void OLED_DrawOnlyString(uint8_t x, uint8_t y, char *str);
void OLED_DrawString(uint8_t x, uint8_t y, const char *fmt, ...);
void OLED_Clearline(uint8_t line);

#endif
