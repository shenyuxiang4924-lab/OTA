/*
 * @Author: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @Date: 2026-04-24 16:22:42
 * @LastEditors: popcorn shenyuxiang4924@gmail.com
 * @LastEditTime: 2026-06-17 17:15:59
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\test1\Hardware\BUTTON.h
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#ifndef __BUTTON_H_
#define __BUTTON_H_

#include <stdint.h>

enum{
    pc0_btn,
    all_btn
};

uint8_t Button_detect(uint8_t btn);

#endif
