# ✅ التحديث: نستخدم نسخة 1.84 (أحدث وأقوى) لحل مشكلة التوافق
FROM rust:1.84-slim-bookworm as builder

# تحسينات لتسريع البناء
WORKDIR /app
COPY . .

# تثبيت مكتبات النظام الضرورية (SSL + Build Tools)
RUN apt-get update && apt-get install -y pkg-config libssl-dev cmake && rm -rf /var/lib/apt/lists/*

# بناء المشروع بأقصى تحسينات (Release Mode)
RUN cargo build --release

# المرحلة 2: التشغيل (The Runner) - نستخدم Bookworm لتوافق أفضل
FROM debian:bookworm-slim

# تثبيت شهادات الأمان و SSL لضمان سرعة الاتصال المشفر
RUN apt-get update && apt-get install -y ca-certificates libssl-dev && rm -rf /var/lib/apt/lists/*

# نسخ الملف التنفيذي من مرحلة البناء
COPY --from=builder /app/target/release/omega_royal /usr/local/bin/omega_royal

# إعدادات البيئة
ENV RUST_LOG=info

# تشغيل البوت
CMD ["omega_royal"]