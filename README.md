# NourivaAI

**AI-Powered Personalized Nutrition Assistant**

NourivaAI คือแอปพลิเคชันผู้ช่วยดูแลสุขภาพและประเมินโภชนาการรายบุคคล ที่ช่วยให้ผู้ใช้บันทึกอาหาร คำนวณสารอาหาร และตรวจสอบข้อมูลโภชนาการโดยอาศัยฐานข้อมูลอาหารและกฎการประเมินที่กำหนดไว้

## Features

- **Food Search** — ค้นหาอาหารจากฐานข้อมูล
- **Barcode Lookup** — ค้นหาข้อมูลอาหารจากบาร์โค้ด และบันทึกรหัสสินค้าที่ไม่พบเพื่อรอตรวจสอบ
- **Nutrition Calculation** — คำนวณสารอาหารจากข้อมูลอาหาร ปริมาณที่รับประทาน และหน่วยที่รองรับ
- **Rule-Based Assessment** — อ่านกฎการประเมินสุขภาพและโภชนาการจากฐานข้อมูล
- **Data Validation** — ตรวจสอบข้อมูล หน่วย และเงื่อนไขก่อนคำนวณ
- **Data Source Tracking** — รองรับการแยกแหล่งที่มาของข้อมูลโภชนาการ
- **Web Interface** — ส่วนติดต่อผู้ใช้ผ่านเว็บเบราว์เซอร์
- **Automated Testing** — ทดสอบการทำงานของ API ด้วย pytest

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, FastAPI |
| API Server | Uvicorn |
| Database | PostgreSQL |
| Database Access | SQLAlchemy |
| Frontend | HTML, CSS, JavaScript |
| Testing | pytest |
| Database Containerization | Docker |

## Project Structure

```text
nouriva-api/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── routes/
│   │   ├── foods.py
│   │   ├── nutrition.py
│   │   └── rules.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── tests/
│   ├── test_foods_barcode.py
│   └── test_nutrition.py
├── .gitignore
└── README.md
```

## System Modules

### 1. Food Management

จัดการการค้นหาและตรวจสอบข้อมูลอาหาร รวมถึงการค้นหาด้วยบาร์โค้ด โดยรหัสสินค้าที่ไม่พบสามารถบันทึกไว้เพื่อรอตรวจสอบก่อนเพิ่มเข้าฐานข้อมูลอาหาร

### 2. Nutrition Calculation

คำนวณปริมาณสารอาหารตามข้อมูลอาหารและปริมาณที่รับประทาน โดยคำนึงถึงฐานการคำนวณและหน่วยที่รองรับ หากข้อมูลที่จำเป็นไม่ครบ ระบบควรระบุข้อจำกัดแทนการสมมติค่าที่ไม่มี

### 3. Rule-Based Assessment

จัดเตรียม API สำหรับอ่านกฎสุขภาพและโภชนาการจากฐานข้อมูล เพื่อใช้เป็นส่วนหนึ่งของกระบวนการประเมิน โดยกฎต้องผ่านเงื่อนไขและสถานะการอนุมัติที่กำหนดก่อนนำไปใช้จริง

### 4. Data Validation and Traceability

ตรวจสอบความถูกต้องของข้อมูลและแหล่งที่มา เพื่อแยกข้อมูลที่ผู้ใช้ยืนยัน ข้อมูลจากฐานข้อมูล และค่าประมาณออกจากกัน

### 5. Web Interface

ให้ผู้ใช้เข้าถึงฟังก์ชันของระบบผ่านเว็บ โดยใช้ HTML, CSS และ JavaScript เชื่อมต่อกับ Backend API

## Health and Nutrition Rules

ระบบออกแบบโดยยึดหลักการสำคัญดังนี้:

- ไม่วินิจฉัยโรคจากข้อมูลอาหารหรือผลตรวจเพียงค่าเดียว
- ไม่ถือว่าข้อมูลสารอาหารที่ขาดหายมีค่าเท่ากับศูนย์
- คำนวณจากปริมาณที่รับประทานจริงและหน่วยที่ถูกต้อง
- แยกข้อมูลที่ยืนยันแล้วออกจากข้อมูลประมาณ
- ไม่ใช้กฎเฉพาะโรคจากการอนุมานโรคโดยอัตโนมัติ
- ไม่สร้างคำแนะนำด้านสุขภาพที่ไม่มีข้อมูลหรือหลักฐานรองรับ

## API Documentation

เมื่อ Backend ทำงาน สามารถเข้าถึง API ได้ผ่าน:

| Endpoint | Purpose |
|---|---|
| `/` | หน้าเว็บของแอปพลิเคชัน |
| `/health/db` | ตรวจสอบการเชื่อมต่อฐานข้อมูล |
| `/rules` | อ่านข้อมูลกฎการประเมิน |
| `/docs` | เอกสาร API แบบ Swagger UI |

## Running the Application

### Prerequisites

- Python
- PostgreSQL
- Docker สำหรับการใช้งานฐานข้อมูลตามการตั้งค่าของโปรเจกต์

### 1. Start the Database

ตรวจสอบให้แน่ใจว่า PostgreSQL container ทำงานอยู่ และตั้งค่าการเชื่อมต่อฐานข้อมูลให้ตรงกับ environment ของโปรเจกต์

### 2. Activate the Python Environment

```bash
cd ~/Downloads/nouriva-api
source .venv/bin/activate
```

### 3. Start the Backend

```bash
python -m uvicorn app.main:app --reload
```

### 4. Open the Application

เปิดเว็บเบราว์เซอร์ไปที่:

- Application: http://127.0.0.1:8000/
- API Documentation: http://127.0.0.1:8000/docs

## Running Tests

รันทดสอบอัตโนมัติด้วยคำสั่ง:

```bash
python -m pytest -v
```

## Data Safety

- ข้อมูลที่จำเป็นต้องใช้ในการเชื่อมต่อระบบควรจัดเก็บใน environment variables
- ห้ามเผยแพร่รหัสผ่าน API keys, access tokens หรือ credentials ใน source code
- ข้อมูลที่ใช้ในการประเมินต้องมีแหล่งที่มาและหน่วยที่เหมาะสม
- ผลการประเมินควรแสดงข้อจำกัดเมื่อข้อมูลไม่เพียงพอ

## Scope

NourivaAI มุ่งเน้นการช่วยบันทึกอาหาร คำนวณสารอาหาร และสนับสนุนการประเมินโภชนาการจากข้อมูลที่มี ไม่ใช่ระบบวินิจฉัยโรคหรือทดแทนคำแนะนำจากบุคลากรทางการแพทย์
