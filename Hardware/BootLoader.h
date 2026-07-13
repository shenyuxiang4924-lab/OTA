#ifndef __BOOTLOADER_H
#define __BOOTLOADER_H

#include "w25q.h"
#include "stdint.h"

typedef struct{
    uint16_t updata;
    uint16_t code_len;
}BootLoader_Head_typedef;

void BootLoader_Run(void);
void BootLoader_OTA_Init(void);
void BootLoader_OTA_Write(uint8_t WriteOver_flag,uint8_t* Code,uint32_t Code_len);

#endif
