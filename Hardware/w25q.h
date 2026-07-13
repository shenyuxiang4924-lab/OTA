/*
 * @Author: popcorn shenyuxiang4924@gmail.com
 * @Date: 2026-05-30 13:00:49
 * @LastEditors: popcorn shenyuxiang4924@gmail.com
 * @LastEditTime: 2026-05-30 14:53:02
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\OTA_Project\OTA\Hardware\w25q.h
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#ifndef __W25Q_H
#define __W25Q_H

#include <stdint.h>

void w25q_Init(void);
void w25q_Read(uint32_t DesAddr, void *pRegAddr, uint16_t len);
void w25q_Write(uint32_t DesAddr, void *pDataAddr, uint16_t len);
void w25q_SectorErase(uint32_t DesAddr);
void w25q_BlockErase(uint32_t DesAddr);
// uint8_t w25q_ReadStatus(uint8_t status);//调试阶段使用
// void w25q_ReadAllStatus(uint8_t* reg);

#endif
