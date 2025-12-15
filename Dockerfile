# المرحلة 1: البناء (The Builder) - نستخدم صورة رسمية لـ Rust
FROM rust:1.75-slim-bullseye as builder

# تحسينات لتسريع البناء
WORKDIR /app
COPY . .

# تثبيت مكتبات النظام الضرورية (SSL + Build Tools)
RUN apt-get update && apt-get install -y pkg-config libssl-dev cmake && rm -rf /var/lib/apt/lists/*

# بناء المشروع بأقصى تحسينات (Release Mode)
RUN cargo build --release

# المرحلة 2: التشغيل (The Runner) - صورة خفيفة جداً وسريعة
FROM debian:bullseye-slim

# تثبيت شهادات الأمان و SSL لضمان سرعة الاتصال المشفر
RUN apt-get update && apt-get install -y ca-certificates libssl-dev && rm -rf /var/lib/apt/lists/*

# نسخ الملف التنفيذي من مرحلة البناء
COPY --from=builder /app/target/release/omega_royal /usr/local/bin/omega_royal

# إعدادات البيئة
ENV RUST_LOG=info

# تشغيل البوت
CMD ["omega_royal"]