#include "MYCAN.h"
#include "can.h"

// #define hcan hcan1

/**
 * @description: 设置CAN过滤器
 * @return {*}
 */
void CAN_Init(void)
{
  HAL_CAN_Start(&hcan);
  CAN_FilterTypeDef FilterConfig;
  FilterConfig.FilterBank = 0;
  FilterConfig.FilterFIFOAssignment = CAN_FILTER_FIFO0;
  FilterConfig.FilterIdHigh = 0x0 << 5; // 掩码过滤器1 最大11位ID：7FF
  FilterConfig.FilterMaskIdHigh = 0x0 << 5;
  FilterConfig.FilterIdLow = 0x0 << 5; // 掩码过滤器2
  FilterConfig.FilterMaskIdLow = 0x0 << 5;
  FilterConfig.FilterMode = CAN_FILTERMODE_IDMASK;
  FilterConfig.FilterScale = CAN_FILTERSCALE_16BIT;
  FilterConfig.FilterActivation = CAN_FILTER_ENABLE;

  HAL_CAN_ConfigFilter(&hcan, &FilterConfig);
  HAL_CAN_ActivateNotification(&hcan,CAN_IT_RX_FIFO0_MSG_PENDING);
}

/**
 * @description: 发送报文（阻塞发送）
 * @param {uint32_t} ID
 * @param {uint8_t} data
 * @param {uint8_t} len
 * @return {*}
 */
void CAN_Transmit(uint32_t ID, uint8_t data[], uint8_t len)
{
  uint32_t TxMailBox;
  CAN_TxHeaderTypeDef TxHeader;
  TxHeader.DLC = len;
  TxHeader.IDE = CAN_ID_STD;
  TxHeader.RTR = CAN_RTR_DATA;
  TxHeader.StdId = ID;

  while (HAL_CAN_GetTxMailboxesFreeLevel(&hcan) == 0)
  {
  }
  HAL_CAN_AddTxMessage(&hcan, &TxHeader, data, &TxMailBox);

  switch (TxMailBox)
  {
  case CAN_TX_MAILBOX0:
  {
    while (!__HAL_CAN_GET_FLAG(&hcan, CAN_FLAG_TXOK0))
    {
    }
    break;
  }
  case CAN_TX_MAILBOX1:
  {
    while (!__HAL_CAN_GET_FLAG(&hcan, CAN_FLAG_TXOK1))
    {
    }
    break;
  }
  case CAN_TX_MAILBOX2:
  {
    while (!__HAL_CAN_GET_FLAG(&hcan, CAN_FLAG_TXOK2))
    {
    }
    break;
  }
  }
}

/**
 * @description: 接收CAN报文(阻塞接收)
 * @param {CANRxMsgTypedef} *rxmsg
 * @param {uint8_t} *num
 * @return {*}
 */
uint8_t CAN_Receive(CANRxMsgTypedef *rxmsg)
{
  CAN_RxHeaderTypeDef RxHeader;
  if (HAL_CAN_GetRxFifoFillLevel(&hcan, CAN_RX_FIFO0) > 0)
  {
    HAL_CAN_GetRxMessage(&hcan, CAN_RX_FIFO0, &RxHeader, rxmsg->data);
    rxmsg->ID = RxHeader.StdId;
    rxmsg->len = RxHeader.DLC;
    return 1;
  }
  else
  {
    return 0;
  }
}

#define rxmsg_len 4
CANRxMsgTypedef rxmsg[rxmsg_len];
volatile uint8_t head, tail = 0;
volatile uint8_t flag_h, flag_t = 0;

uint8_t rxmsg_IsFull(void)
{
  if (flag_h != flag_t && head == tail)
  {
    return 1;
  }
  else
  {
    return 0;
  }
}

uint8_t rxmsg_IsEmpty(void)
{
  if (flag_h == flag_t && head == tail)
  {
    return 1;
  }
  else
  {
    return 0;
  }
}

CANRxMsgTypedef rxmsg_pop(void)
{
  CANRxMsgTypedef res = rxmsg[head];
  head++;
  if (head == rxmsg_len)
  {
    head = 0;
    flag_h = (flag_h + 1) % 2;
  }
  return res;
}

void rxmsg_push(CANRxMsgTypedef arxmsg) // 需在os层加入临界区保护
{
  rxmsg[tail] = arxmsg;
  tail++;
  if (tail == rxmsg_len)
  {
    tail = 0;
    flag_t = (flag_t + 1) % 2;
  }
}

uint8_t CAN_Receive_IT(CANRxMsgTypedef *arxmsg)
{
  if (rxmsg_IsEmpty() != 1)
  {
    *arxmsg = rxmsg_pop();
    return 1;
  }
  else
  {
    return 0;
  }
}

// void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan)
// {
//   if (hcan->Instance == CAN1)
//   {
//     CAN_RxHeaderTypeDef RxHeader;
//     CANRxMsgTypedef arxmsg;
//     if (HAL_CAN_GetRxFifoFillLevel(hcan, CAN_RX_FIFO0) > 0)
//     {
//       if (rxmsg_IsFull() != 1)
//       {
//         HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO0, &RxHeader, arxmsg.data);
//         arxmsg.ID = RxHeader.StdId;
//         arxmsg.len = RxHeader.DLC;
//         rxmsg_push(arxmsg);
//       }
//     }
//   }
// }
