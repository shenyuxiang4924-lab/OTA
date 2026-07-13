/*
 * @Author: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @Date: 2026-04-26 15:48:52
 * @LastEditors: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
 * @LastEditTime: 2026-04-29 14:47:53
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\master\Hardware\MYCAN.h
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#ifndef __MYCAN_H_
#define __MYCAN_H_

#include <stdint.h>

typedef struct {
  uint8_t data[8];
  uint32_t ID;
  uint8_t len;
}CANRxMsgTypedef;

void CAN_Init(void);
void CAN_Transmit(uint32_t ID, uint8_t data[], uint8_t len);
uint8_t CAN_Receive(CANRxMsgTypedef* rxmsg);
uint8_t CAN_Receive_IT(CANRxMsgTypedef *arxmsg);

#endif
