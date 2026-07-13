/*
 * @Author: popcorn shenyuxiang4924@gmail.com
 * @Date: 2026-06-03 20:40:53
 * @LastEditors: nikibikikii-star nikibikikii@gmail.com
 * @LastEditTime: 2026-07-09 14:43:06
 * @FilePath: \MDK-ARMc:\Users\syx23\Desktop\OTA_Project\BootLoader\Hardware\BootLoader.c
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
#include "BootLoader.h"
#include "OLED.h"
#include "main.h"
#include "stdio.h"
#include "BUTTON.h"

// #define FlashAddr_Head 0x000000
// #define FlashAddr_Code 0x010000
#define FlashSize_Sector 0x001000
#define FlashSize_Block 0x010000
#define KernelAddr_Stack 0x20000000
#define KernelSize_Stack 0x00010000
#define KernelSize_App 0x0007c000
#define KernelSize_Page 0x00000800
#define KernelAddr_App 0x08004000
#define Buffer_Len 256

typedef struct
{
    uint8_t Code_State;
    uint32_t Code_Size;
} Head_typedef;

typedef struct
{
    uint32_t FlashAddr_Code;
    uint32_t FlashAddr_Head;
    Head_typedef Code_Head;
} CodeBlock_typedef;

typedef enum
{
    state_empty,
    state_new,
    state_last,
    state_cur,
    state_error
} CodeBlock_State;

static CodeBlock_typedef CodeA = {FlashSize_Block * 1, FlashSize_Sector * 1};
static CodeBlock_typedef CodeB = {FlashSize_Block * 2, FlashSize_Sector * 2};
static CodeBlock_typedef CodeC = {FlashSize_Block * 3, FlashSize_Sector * 3};
static CodeBlock_typedef CodeD = {FlashSize_Block * 4, FlashSize_Sector * 4};
static CodeBlock_typedef *CodeBlocks[4] = {&CodeA, &CodeB, &CodeC, &CodeD};

#define empty_size 4
static CodeBlock_typedef *new = NULL, *cur = NULL, *last = NULL, *error = NULL;
static CodeBlock_typedef *empty[empty_size];
static uint8_t empty_head = 0;
static uint8_t empty_tail = 0;
static uint8_t empty_turn_flag = 0;

typedef void (*pFunc)(void);

typedef enum
{
    BL_TEST,
    BL_UPDATA,
    BL_NO_UPDATA,
    BL_FLASH_ERASE_ERR,
    BL_FLASH_WRITE_ERR,
    BL_ROLLBACK_REQUEST,
    BL_ROLLBACK,
    BL_JUMP2APP,
    BL_APP_INVALID,
    BL_REPAIR,
    BL_ROLLBACK_ERR,
    BL_Status_Num
} BootLoader_Status;

typedef enum
{
    updata_flag,
    code_len_flag,
    flag_num
} Head_Flag;

uint8_t is_ept_empty(void)
{
    if ((empty_head == empty_tail) && (empty_turn_flag == 0))
    {
        return 1;
    }
    return 0;
}

uint8_t is_ept_full(void)
{
    if ((empty_head == empty_tail) && (empty_turn_flag == 1))
    {
        return 1;
    }
    return 0;
}

uint8_t ept_push(CodeBlock_typedef *Code)
{
    if (is_ept_full() == 1)
    {
        return 0;
    }
    empty[empty_tail] = Code;
    empty_tail++;
    if (empty_tail >= empty_size)
    {
        empty_tail = 0;
        empty_turn_flag = (empty_turn_flag + 1) % 2;
    }
    return 1;
}

uint8_t ept_pop(CodeBlock_typedef **Code)
{
    if (is_ept_empty() == 1)
    {
        return 0;
    }
    *Code = empty[empty_head];
    empty_head++;
    if (empty_head >= empty_size)
    {
        empty_head = 0;
        empty_turn_flag = (empty_turn_flag + 1) % 2;
    }
    return 1;
}

uint8_t Flag_Offset[flag_num] = {0, 2};

void BootLoader_Test(BootLoader_Status *Cur_Status)
{
    cur = NULL;
    new = NULL;
    last = NULL;
    empty_head = 0;
    empty_tail = 0;
    empty_turn_flag = 0;
    for (int i = 0; i < 4; i++)
    {
        w25q_Read(CodeBlocks[i]->FlashAddr_Head, &CodeBlocks[i]->Code_Head, sizeof(Head_typedef));
        if (CodeBlocks[i]->Code_Head.Code_State == state_cur)
        {
            cur = CodeBlocks[i];
        }
        else if (CodeBlocks[i]->Code_Head.Code_State == state_new)
        {
            new = CodeBlocks[i];
        }
        else if (CodeBlocks[i]->Code_Head.Code_State == state_last)
        {
            last = CodeBlocks[i];
        }
        else if (CodeBlocks[i]->Code_Head.Code_State == state_error)
        {
            error = CodeBlocks[i];
        }
        else
        {
            ept_push(CodeBlocks[i]);
        }
    }
    if (error != NULL)
    {
        *Cur_Status = BL_REPAIR;
    }
    else if (new != NULL)
    {
        *Cur_Status = BL_UPDATA;
    }
    else
    {
        *Cur_Status = BL_NO_UPDATA;
    }
}

void BootLoader_Updata(BootLoader_Status *Cur_Status)
{
    w25q_Read(new->FlashAddr_Head, &new->Code_Head, sizeof(Head_typedef));
    uint32_t cds = new->Code_Head.Code_Size;

    if (cds > 0)
    {
        FLASH_EraseInitTypeDef erase_init;
        uint32_t erase_error = 0;
        erase_init.Banks = FLASH_BANK_1;
        erase_init.NbPages = (cds - 1) / KernelSize_Page + 1;
        erase_init.PageAddress = KernelAddr_App;
        erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
        HAL_FLASH_Unlock();
        if (HAL_FLASHEx_Erase(&erase_init, &erase_error) == HAL_OK)
        {
            uint32_t code_remain_len = cds;
            uint32_t FlashAddr_Code_offset = new->FlashAddr_Code;
            uint32_t KernelAddr_App_offset = KernelAddr_App;
            while (code_remain_len > 0)
            {
                uint8_t Buffer[Buffer_Len];
                if (code_remain_len >= Buffer_Len)
                {
                    w25q_Read(FlashAddr_Code_offset, Buffer, Buffer_Len);
                    FlashAddr_Code_offset += Buffer_Len;
                    uint32_t write_len = Buffer_Len;
                    for (int i = 0; i < write_len; i += 2)
                    {
                        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_HALFWORD, KernelAddr_App_offset, (uint16_t)Buffer[i] | (Buffer[i + 1] << 8)) == HAL_OK)
                        {
                            KernelAddr_App_offset = KernelAddr_App_offset + 2;
                            code_remain_len -= 2;
                        }
                        else
                        {
                            HAL_FLASH_Lock();
                            *Cur_Status = BL_FLASH_WRITE_ERR;
                            return;
                        }
                    }
                }
                else
                {
                    w25q_Read(FlashAddr_Code_offset, Buffer, code_remain_len);
                    FlashAddr_Code_offset += code_remain_len;
                    uint32_t write_len = code_remain_len;
                    for (int i = 0; i < write_len; i += 2)
                    {
                        if (i + 1 < write_len)
                        {
                            if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_HALFWORD, KernelAddr_App_offset, (uint16_t)Buffer[i] | (Buffer[i + 1] << 8)) == HAL_OK)
                            {
                                KernelAddr_App_offset = KernelAddr_App_offset + 2;
                                code_remain_len -= 2;
                            }
                            else
                            {
                                HAL_FLASH_Lock();
                                *Cur_Status = BL_FLASH_WRITE_ERR;
                                return;
                            }
                        }
                        else if (i + 1 >= write_len)
                        {
                            if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_HALFWORD, KernelAddr_App_offset, (uint16_t)Buffer[i] | (0xff << 8)) == HAL_OK)
                            {
                                KernelAddr_App_offset = KernelAddr_App_offset + 2;
                                code_remain_len = code_remain_len - 1;
                            }
                            else
                            {
                                HAL_FLASH_Lock();
                                *Cur_Status = BL_FLASH_WRITE_ERR;
                                return;
                            }
                        }
                    }
                }
            }
            HAL_FLASH_Lock();
            if (last != NULL)
            {
                w25q_BlockErase(last->FlashAddr_Code);
                w25q_SectorErase(last->FlashAddr_Head);
                ept_push(last);
            }
            last = cur;
            if (cur != NULL)
            {
                cur->Code_Head.Code_State = state_last;
                w25q_Write(cur->FlashAddr_Head, &cur->Code_Head, sizeof(Head_typedef));
            }
            cur = new;
            if (new != NULL)
            {
                new->Code_Head.Code_State = state_error;
                w25q_Write(new->FlashAddr_Head, &new->Code_Head, sizeof(Head_typedef));
            }
            new = NULL;
            *Cur_Status = BL_NO_UPDATA;
        }
        else
        {
            HAL_FLASH_Lock();
            *Cur_Status = BL_FLASH_ERASE_ERR;
        }
    }
}

void BootLoader_Repair(BootLoader_Status *Cur_Status)
{
    if(last==NULL){
        *Cur_Status = BL_FLASH_ERASE_ERR;
        return;
    }

    w25q_Read(last->FlashAddr_Head, &last->Code_Head, sizeof(Head_typedef));
    uint32_t cds = last->Code_Head.Code_Size;

    if (cds > 0)
    {
        FLASH_EraseInitTypeDef erase_init;
        uint32_t erase_error = 0;
        erase_init.Banks = FLASH_BANK_1;
        erase_init.NbPages = (cds - 1) / KernelSize_Page + 1;
        erase_init.PageAddress = KernelAddr_App;
        erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
        HAL_FLASH_Unlock();
        if (HAL_FLASHEx_Erase(&erase_init, &erase_error) == HAL_OK)
        {
            uint32_t code_remain_len = cds;
            uint32_t FlashAddr_Code_offset = last->FlashAddr_Code;
            uint32_t KernelAddr_App_offset = KernelAddr_App;
            while (code_remain_len > 0)
            {
                uint8_t Buffer[Buffer_Len];
                if (code_remain_len >= Buffer_Len)
                {
                    w25q_Read(FlashAddr_Code_offset, Buffer, Buffer_Len);
                    FlashAddr_Code_offset += Buffer_Len;
                    uint32_t write_len = Buffer_Len;
                    for (int i = 0; i < write_len; i += 2)
                    {
                        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_HALFWORD, KernelAddr_App_offset, (uint16_t)Buffer[i] | (Buffer[i + 1] << 8)) == HAL_OK)
                        {
                            KernelAddr_App_offset = KernelAddr_App_offset + 2;
                            code_remain_len -= 2;
                        }
                        else
                        {
                            HAL_FLASH_Lock();
                            *Cur_Status = BL_FLASH_WRITE_ERR;
                            return;
                        }
                    }
                }
                else
                {
                    w25q_Read(FlashAddr_Code_offset, Buffer, code_remain_len);
                    FlashAddr_Code_offset += code_remain_len;
                    uint32_t write_len = code_remain_len;
                    for (int i = 0; i < write_len; i += 2)
                    {
                        if (i + 1 < write_len)
                        {
                            if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_HALFWORD, KernelAddr_App_offset, (uint16_t)Buffer[i] | (Buffer[i + 1] << 8)) == HAL_OK)
                            {
                                KernelAddr_App_offset = KernelAddr_App_offset + 2;
                                code_remain_len -= 2;
                            }
                            else
                            {
                                HAL_FLASH_Lock();
                                *Cur_Status = BL_FLASH_WRITE_ERR;
                                return;
                            }
                        }
                        else if (i + 1 >= write_len)
                        {
                            if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_HALFWORD, KernelAddr_App_offset, (uint16_t)Buffer[i] | (0xff << 8)) == HAL_OK)
                            {
                                KernelAddr_App_offset = KernelAddr_App_offset + 2;
                                code_remain_len = code_remain_len - 1;
                            }
                            else
                            {
                                HAL_FLASH_Lock();
                                *Cur_Status = BL_FLASH_WRITE_ERR;
                                return;
                            }
                        }
                    }
                }
            }
            HAL_FLASH_Lock();
            if (error != NULL)
            {
                w25q_BlockErase(error->FlashAddr_Code);
                w25q_SectorErase(error->FlashAddr_Head);
                ept_push(error);
            }
            error = NULL;
            if (last != NULL)
            {
                last->Code_Head.Code_State = state_cur;
                w25q_Write(last->FlashAddr_Head, &last->Code_Head, sizeof(Head_typedef));
            }
            cur = last;
            last = NULL;
            *Cur_Status = BL_TEST;
        }
        else
        {
            HAL_FLASH_Lock();
            *Cur_Status = BL_FLASH_ERASE_ERR;
        }
    }
}

void BootLoader_NO_UPDATA(BootLoader_Status *Cur_Status)
{
    *Cur_Status = BL_JUMP2APP;
}

void BootLoader_JUMP2APP(BootLoader_Status *Cur_Status)
{
    uint32_t Stack_addr = *(uint32_t *)(KernelAddr_App);
    uint32_t Reset_addr = *(uint32_t *)(KernelAddr_App + 4);
    pFunc App_reset = (pFunc)Reset_addr;

    if ((Stack_addr >= KernelAddr_Stack) &&
        (Stack_addr < KernelAddr_Stack + KernelSize_Stack) &&
        (Reset_addr >= KernelAddr_App) &&
        (Reset_addr < KernelAddr_App + KernelSize_App)) // 健壮性判断
    {
        __disable_irq(); // 关中断

        SysTick->CTRL = 0; // 关闭systick
        SysTick->LOAD = 0;
        SysTick->VAL = 0;
        for (int i = 0; i < 8; i++) // 关闭nvic
        {
            NVIC->ICER[i] = 0xffffffff;
            NVIC->ICPR[i] = 0xffffffff;
        }

        HAL_DeInit(); // 关闭外设

        SCB->VTOR = KernelAddr_App; // 设置中断向量表基地址
        __set_MSP(Stack_addr);      // 设置堆栈指针

        __enable_irq(); // 开中断
        App_reset();    // 执行跳转
    }
    else
    {
        *Cur_Status = BL_APP_INVALID;
    }
}

void BootLoader_Run(void)
{
    w25q_Init();
    OLED_Init();
    BootLoader_Status Cur_Status = BL_TEST;

    while (1)
    {
        switch (Cur_Status)
        {
        case BL_TEST:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "Test");
            OLED_Map();
            BootLoader_Test(&Cur_Status);
            HAL_Delay(500);
            break;
        }
        case BL_REPAIR:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "Repair");
            OLED_Map();
            BootLoader_Repair(&Cur_Status);
            HAL_Delay(500);
            break;
        }
        case BL_UPDATA:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "Update");
            OLED_Map();
            BootLoader_Updata(&Cur_Status);
            HAL_Delay(500);
            break;
        }
        case BL_NO_UPDATA:
        {
            BootLoader_NO_UPDATA(&Cur_Status);
            break;
        }
        case BL_JUMP2APP:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "Jump");
            OLED_Map();
            BootLoader_JUMP2APP(&Cur_Status);
            HAL_Delay(500);
            break;
        }
        case BL_FLASH_ERASE_ERR:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "Erase Err");
            OLED_Map();
            HAL_Delay(500);
            break;
        }
        case BL_FLASH_WRITE_ERR:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "Write Err");
            OLED_Map();
            HAL_Delay(500);
            break;
        }
        case BL_APP_INVALID:
        {
            OLED_Clearline(3);
            OLED_DrawOnlyString(3, 0, "App Invalid");
            OLED_Map();
            HAL_Delay(500);
            break;
        }
        }
    }
}

void BootLoader_OTA_BlockState_print(void)
{
    char *str[4] = {"A: ", "B: ", "C: ", "D: "};
    for (int i = 0; i < 4; i++)
    {
        if (i % 2 == 0)
        {
            OLED_Clearline(i / 2);
        }
        switch (CodeBlocks[i]->Code_Head.Code_State)
        {
        case state_new:
        {
            OLED_DrawString(i / 2, i % 2 * 8, "%snew", str[i]);
            break;
        }
        case state_cur:
        {
            OLED_DrawString(i / 2, i % 2 * 8, "%scur", str[i]);
            break;
        }
        case state_last:
        {
            OLED_DrawString(i / 2, i % 2 * 8, "%slas", str[i]);
            break;
        }
        case state_error:
        {
            OLED_DrawString(i / 2, i % 2 * 8, "%serr", str[i]);
            break;
        }
        default:
        {
            OLED_DrawString(i / 2, i % 2 * 8, "%sept", str[i]);
            break;
        }
        }
        OLED_Map();
    }
}

void BootLoader_OTA_Init(void)
{
    w25q_Init();
    OLED_Init();

    CodeBlock_typedef *CodeBlocks[4] = {&CodeA, &CodeB, &CodeC, &CodeD};
    for (int i = 0; i < 4; i++)
    {
        w25q_Read(CodeBlocks[i]->FlashAddr_Head, &CodeBlocks[i]->Code_Head, sizeof(Head_typedef));
        if (CodeBlocks[i]->Code_Head.Code_State == state_cur)
        {
            cur = CodeBlocks[i];
        }
        else if (CodeBlocks[i]->Code_Head.Code_State == state_new)
        {
            new = CodeBlocks[i];
        }
        else if (CodeBlocks[i]->Code_Head.Code_State == state_last)
        {
            last = CodeBlocks[i];
        }
        else if (CodeBlocks[i]->Code_Head.Code_State == state_error)
        {
            error = CodeBlocks[i];
        }
        else
        {
            ept_push(CodeBlocks[i]);
        }

        // 完成初始化，清除error
        if (error != NULL)
        {
            error->Code_Head.Code_State = state_cur;
            w25q_Write(error->FlashAddr_Head, &error->Code_Head, sizeof(Head_typedef));
            cur=error;
            error=NULL;
        }
    }

    BootLoader_OTA_BlockState_print();
}

void BootLoader_OTA_Write(uint8_t WriteOver_flag, uint8_t *Code, uint32_t Code_len)
{
    static uint32_t FlashAddr_Code_offset;
    static uint32_t cds;
    static uint8_t WriteOver_lastflag = 1;
    static CodeBlock_typedef *pCodeBlock;
    if ((WriteOver_lastflag == 1) && (WriteOver_flag == 0)) // 收到新固件
    {
        if (ept_pop(&pCodeBlock) == 0)
        {
            return;
        }
        FlashAddr_Code_offset = pCodeBlock->FlashAddr_Code;
        cds = 0;
    }
    WriteOver_lastflag = WriteOver_flag;

    if (WriteOver_flag == 0) // 固件接收未结束
    {
        w25q_Write(FlashAddr_Code_offset, Code, Code_len);
        FlashAddr_Code_offset += Code_len;
        cds += Code_len;

        OLED_Clearline(2);
        OLED_DrawString(2, 0, "rec:%d", cds);
        OLED_Clearline(3);
        OLED_DrawString(3, 0, "coding");
        OLED_Map();
    }
    else if (WriteOver_flag == 1) // 固件接收结束
    {
        pCodeBlock->Code_Head.Code_Size = cds;
        pCodeBlock->Code_Head.Code_State = state_new;
        w25q_Write(pCodeBlock->FlashAddr_Head, &pCodeBlock->Code_Head, sizeof(Head_typedef));
        if (new != NULL)
        {
            w25q_BlockErase(new->FlashAddr_Code);
            w25q_SectorErase(new->FlashAddr_Head);
            ept_push(new);
            new->Code_Head.Code_State = state_empty;
        }
        new = pCodeBlock;

        OLED_Clearline(3);
        OLED_DrawString(3, 0, "code over");
        OLED_Map();

        BootLoader_OTA_BlockState_print();
    }
}
