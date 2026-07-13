/*
 * @Author: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @Date: 2026-04-24 16:22:06
 * @LastEditors: popcorn shenyuxiang4924@gmail.com
 * @LastEditTime: 2026-06-17 17:22:27
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\test1\Hardware\BUTTON.c
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
/*
 * @Author: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @Date: 2026-04-24 16:22:06
 * @LastEditors: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @LastEditTime: 2026-04-24 17:12:41
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\test1\Hardware\BUTTON.c
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#include "BUTTON.h"
#include "gpio.h"

typedef struct
{
    GPIO_TypeDef *GPIOx;
    uint16_t GPIO_Pin;
} Button_TypeDef;

Button_TypeDef pc0_button = {GPIOC, GPIO_PIN_0};

Button_TypeDef *Buttons[all_btn] = {&pc0_button};

uint8_t Button_detect(uint8_t btn)
{ // gpio输入采用下拉输入
    if (btn == all_btn)
    {
        uint8_t reg = 0;
        for (int i = 0; i < all_btn; i++)
        {
            reg = (reg << 1) | HAL_GPIO_ReadPin(Buttons[i]->GPIOx, Buttons[i]->GPIO_Pin);
        }
        HAL_Delay(50);
        for (int i = 0; i < all_btn; i++)
        {
            if ((reg>>(all_btn-1-i))&1 != HAL_GPIO_ReadPin(Buttons[i]->GPIOx, Buttons[i]->GPIO_Pin))
            {
                reg=reg&~(1<<(all_btn-1-i));
            }
        }
        return reg;
    }
    else
    {
        uint8_t reg = HAL_GPIO_ReadPin(Buttons[btn]->GPIOx, Buttons[btn]->GPIO_Pin);
        HAL_Delay(50);
        if (reg == HAL_GPIO_ReadPin(Buttons[btn]->GPIOx, Buttons[btn]->GPIO_Pin))
        {
            return reg;
        }
        else
        {
            return 0;
        }
    }
}
