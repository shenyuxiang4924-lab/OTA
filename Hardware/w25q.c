/*
 * @Author: popcorn shenyuxiang4924@gmail.com
 * @Date: 2026-05-30 13:00:49
 * @LastEditors: popcorn shenyuxiang4924@gmail.com
 * @LastEditTime: 2026-06-14 23:10:57
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\OTA_Project\OTA\Hardware\w25q128.c
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#include "w25q.h"
#include "spi.h"
#include "gpio.h"
#include "string.h"

#define hspi &hspi2
#define FlashSize_Page 0x000100
#define FlashSize_Sector 0x001000

#define CS_high() HAL_GPIO_WritePin(GPIOB, GPIO_PIN_12, GPIO_PIN_SET)
#define CS_low() HAL_GPIO_WritePin(GPIOB, GPIO_PIN_12, GPIO_PIN_RESET)

static const uint8_t Instruction[] = {0x03,
                                      0x05,
                                      0x35,
                                      0x15,
                                      0xD8,
                                      0x20,
                                      0x02,
                                      0x06};
enum
{
    Read_data,
    Read_status1,
    Read_status2,
    Read_status3,
    Erase_Block,
    Erase_Sector,
    Write_data,
    Write_Enable,
    All_num
};

uint8_t w25q_ReadStatus(uint8_t status)
{
    CS_low();
    uint8_t reg = 0;
    if (status == 1)
    {
        HAL_SPI_Transmit(hspi, &Instruction[Read_status1], 1, 1000);
        HAL_SPI_Receive(hspi, &reg, 1, 1000);
    }
    else if (status == 2)
    {
        HAL_SPI_Transmit(hspi, &Instruction[Read_status2], 1, 1000);
        HAL_SPI_Receive(hspi, &reg, 1, 1000);
    }
    else if (status == 3)
    {
        HAL_SPI_Transmit(hspi, &Instruction[Read_status3], 1, 1000);
        HAL_SPI_Receive(hspi, &reg, 1, 1000);
    }
    CS_high();
    return reg;
}

uint8_t w25q_IsBusy(void)
{

    if ((w25q_ReadStatus(1) >> 0) & 1 == 1)
    {
        return 1;
    }
    else
    {
        return 0;
    }
}

void w25q_ReadAllStatus(uint8_t *reg)
{
    reg[0] = w25q_ReadStatus(1);
    reg[1] = w25q_ReadStatus(2);
    reg[2] = w25q_ReadStatus(3);
}

void w25q_WriteEnable(void)
{
    while (w25q_IsBusy() == 1)
    {
        HAL_Delay(1);
    }
    CS_low();
    HAL_SPI_Transmit(hspi, &Instruction[Write_Enable], 1, 1000);
    CS_high();
}

void w25q_Read(uint32_t DesAddr, void *pRegAddr, uint16_t len)
{
    uint8_t reg[256] = {0};
    uint8_t pDesAddr[3] = {(uint8_t)((DesAddr >> 16) & 0xff),
                           (uint8_t)((DesAddr >> 8) & 0xff),
                           (uint8_t)((DesAddr >> 0) & 0xff)};
    while (w25q_IsBusy() == 1)
    {
        HAL_Delay(1);
    }
    CS_low();
    HAL_SPI_Transmit(hspi, &Instruction[Read_data], 1, 1000);
    HAL_SPI_Transmit(hspi, pDesAddr, 3, 1000);
    HAL_SPI_Receive(hspi, reg, len, 1000);
    CS_high();
    memcpy(pRegAddr, reg, len);
}

void w25q_BlockErase(uint32_t DesAddr)
{
    uint8_t pDesAddr[3] = {(uint8_t)((DesAddr >> 16) & 0xff),
                           (uint8_t)((DesAddr >> 8) & 0xff),
                           (uint8_t)((DesAddr >> 0) & 0xff)};
    w25q_WriteEnable();
    while (w25q_IsBusy() == 1)
    {
        HAL_Delay(1);
    }
    CS_low();
    HAL_SPI_Transmit(hspi, &Instruction[Erase_Block], 1, 1000);
    HAL_SPI_Transmit(hspi, pDesAddr, 3, 1000);
    CS_high();
}

void w25q_SectorErase(uint32_t DesAddr)
{
    uint8_t pDesAddr[3] = {(uint8_t)((DesAddr >> 16) & 0xff),
                           (uint8_t)((DesAddr >> 8) & 0xff),
                           (uint8_t)((DesAddr >> 0) & 0xff)};
    w25q_WriteEnable();
    while (w25q_IsBusy() == 1)
    {
        HAL_Delay(1);
    }
    CS_low();
    HAL_SPI_Transmit(hspi, &Instruction[Erase_Sector], 1, 1000);
    HAL_SPI_Transmit(hspi, pDesAddr, 3, 1000);
    CS_high();
}

void w25q_Init(void)
{
    CS_high();
}

void w25q_Write(uint32_t DesAddr, void *pDataAddr, uint16_t len)
{
    uint8_t reg[256] = {0};
    uint32_t StartAddr = DesAddr;
    uint32_t EndAddr = DesAddr + len - 1;
    uint16_t sector_num = ((EndAddr - EndAddr % FlashSize_Sector + FlashSize_Sector) - (StartAddr - StartAddr % FlashSize_Sector)) / FlashSize_Sector;
    for (int i = 0; i < sector_num; i++)
    {
        uint32_t curSectorStartAddr = StartAddr - StartAddr % FlashSize_Sector;
        uint32_t curSectorEndAddr = curSectorStartAddr + FlashSize_Sector - 1;
        uint8_t sector_erase_flag = 0;
        uint16_t page_num;
        if (EndAddr > curSectorEndAddr) // 当前扇区写不完
        {
            page_num = ((curSectorEndAddr - curSectorEndAddr % FlashSize_Page + FlashSize_Page) - (StartAddr - StartAddr % FlashSize_Page)) / FlashSize_Page;
        }
        else // 当前扇区能写完
        {
            page_num = ((EndAddr - EndAddr % FlashSize_Page + FlashSize_Page) - (StartAddr - StartAddr % FlashSize_Page)) / FlashSize_Page;
        }
        for (int j = 0; j < page_num; j++)
        {
            uint16_t reg_len;
            if (EndAddr > (StartAddr - StartAddr % FlashSize_Page + FlashSize_Page - 1))
            {
                w25q_Read(StartAddr, reg, FlashSize_Page - StartAddr % FlashSize_Page);
                reg_len = FlashSize_Page - StartAddr % FlashSize_Page;
            }
            else
            {
                w25q_Read(StartAddr, reg, EndAddr - StartAddr + 1);
                reg_len = EndAddr - StartAddr + 1;
            }
            for (int l = 0; l < reg_len; l++)
            {
                if (reg[l] != 0xff)
                {
                    w25q_SectorErase(StartAddr);
                    sector_erase_flag = 1;
                    break;
                }
            }
            StartAddr += reg_len;
            if (sector_erase_flag == 1)
            {
                break;
            }
        }
        for (int j = 0; j < page_num; j++)
        {
            uint16_t write_len = 0;
            w25q_WriteEnable();
            while (w25q_IsBusy() == 1)
            {
                HAL_Delay(1);
            }
            CS_low();
            HAL_SPI_Transmit(hspi, &Instruction[Write_data], 1, 1000);
            uint8_t pDesAddr[3] = {(uint8_t)((DesAddr >> 16) & 0xff),
                                   (uint8_t)((DesAddr >> 8) & 0xff),
                                   (uint8_t)((DesAddr >> 0) & 0xff)};
            HAL_SPI_Transmit(hspi, pDesAddr, 3, 1000);
            if (EndAddr > DesAddr - DesAddr % FlashSize_Page + FlashSize_Page - 1)
            {
                HAL_SPI_Transmit(hspi, pDataAddr, FlashSize_Page - DesAddr % FlashSize_Page, 1000);
                write_len = FlashSize_Page - DesAddr % FlashSize_Page;
            }
            else
            {
                HAL_SPI_Transmit(hspi, pDataAddr, EndAddr - DesAddr + 1, 1000);
                write_len = EndAddr - DesAddr+1;
            }
            DesAddr += write_len;
            pDataAddr = (uint8_t *)pDataAddr + write_len;
            CS_high();
        }
    }
}
