# MT5 Python Bridge API

นี่คือโปรแกรม API น้ำหนักเบาที่ทำหน้าที่เป็นสะพานเชื่อม (Bridge) ระหว่างโปรเจกต์ Forwardtest ของคุณ และโปรแกรม MetaTrader 5 (MT5)

## วิธีการติดตั้งบน Windows VPS (LightNode)

### 1. สิ่งที่ต้องติดตั้งบน Windows VPS ก่อน
1. **โปรแกรม MetaTrader 5:** โหลดจากโบรกเกอร์ของคุณและติดตั้งให้เรียบร้อย (และล็อกอินบัญชีเทรดไว้)
2. **Python:** ดาวน์โหลดจาก [python.org](https://www.python.org/downloads/windows/) (ตอนติดตั้งอย่าลืมติ๊กกล่อง `Add python.exe to PATH`)
3. **เปิด Auto Trading ใน MT5:** 
   - ไปที่ `Tools > Options > Expert Advisors` 
   - ติ๊กถูกที่ `Allow algorithmic trading`

### 2. การรันโปรแกรม Bridge นี้
1. ก๊อปปี้โฟลเดอร์ `mt5-bridge` นี้ไปไว้บน Windows VPS
2. เปิดโปรแกรม **Command Prompt** (cmd) หรือ **PowerShell** บน VPS
3. พิมพ์คำสั่งเข้าไปในโฟลเดอร์นี้:
   ```cmd
   cd path\to\mt5-bridge
   ```
4. ติดตั้งไลบรารีที่จำเป็น:
   ```cmd
   pip install -r requirements.txt
   ```
5. รันเซิร์ฟเวอร์ API:
   ```cmd
   python main.py
   ```
*(หน้าต่าง CMD นี้จะต้องเปิดทิ้งไว้คู่กับหน้าต่างโปรแกรม MT5 เสมอ)*

### 3. การทดสอบยิง API (ตัวอย่าง)
เมื่อรันสำเร็จ API จะเปิดอยู่ที่ `http://localhost:8000` (หรือใช้ IP ของ VPS ในการยิงจากภายนอก)

**เช็คสถานะการเชื่อมต่อ:**
```bash
GET http://<VPS_IP>:8000/
```

**ส่งคำสั่ง Buy/Sell:**
```bash
POST http://<VPS_IP>:8000/trade
Content-Type: application/json

{
    "symbol": "XAUUSD",
    "action": "buy",
    "volume": 0.01,
    "sl": 1900.50,
    "tp": 2000.00,
    "comment": "AI_Bot_Order"
}
```

### ⚠️ หมายเหตุความปลอดภัย
หากคุณเปิด Port 8000 ให้ยิงเข้ามจากภายนอก VPS แนะนำให้เพิ่มระบบ Token (API Key) เพื่อป้องกันคนอื่นแอบยิงคำสั่งเข้ามาเทรดเงินของคุณครับ (ในโค้ดปัจจุบันทำไว้แบบง่ายๆ เพื่อการทดสอบก่อน)
