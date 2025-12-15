use std::collections::{HashMap, VecDeque};
use std::env;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{Mutex, mpsc};
use tokio::time::sleep;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use futures_util::{StreamExt, SinkExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use dotenv::dotenv;
use std::fs;
use chrono::{DateTime, Utc};

// --- Config Constants ---
const MEXC_BASE_URL: &str = "https://api.mexc.com";
const MEXC_WS_URL: &str = "wss://wbs.mexc.com/ws";
const SYMBOLS_PER_SOCKET: usize = 30; 

// --- Structures ---

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Trade {
    symbol: String,
    buy_price: f64,
    peak_price: f64,
    quantity: f64,
    timestamp: u64,
    entry_time_str: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ClosedTrade {
    symbol: String,
    pnl_percent: f64,
    profit_usdt: f64,
    close_time: String,
}

#[derive(Debug)]
enum TradeAction {
    Buy { symbol: String, price: f64 },
    Sell { symbol: String, price: f64, qty: f64, buy_price: f64 },
}

struct AppState {
    active_trades: HashMap<String, Trade>,
    closed_trades: Vec<ClosedTrade>, // سجل الصفقات للتقارير
    price_windows: HashMap<String, VecDeque<(u64, f64)>>, 
    config: Config,
    // System Status Flags
    is_running: bool,          // هل النظام يعمل الآن؟
    waiting_for_amount: bool,  // هل ننتظر إدخال المبلغ؟
    last_update_id: u64,       // لتليجرام
}

#[derive(Clone)]
struct Config {
    api_key: String,
    api_secret: String,
    bot_token: String,
    chat_id: String,
    trade_amount: f64, // يتم تحديثه ديناميكياً بأمرك
}

// --- Helper Functions ---

fn get_timestamp_secs() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()
}

fn get_current_time_str() -> String {
    let now: DateTime<Utc> = SystemTime::now().into();
    now.format("%Y-%m-%d %H:%M:%S").to_string()
}

fn sign_query(query: &str, secret: &str) -> String {
    type HmacSha256 = Hmac<Sha256>;
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).expect("HMAC error");
    mac.update(query.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

// --- Core Logic ---

impl AppState {
    fn new(cfg: Config) -> Self {
        // تحميل الصفقات السابقة من الملف المحلي (Local Directory)
        let trades = if let Ok(data) = fs::read_to_string("active_trades.json") {
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            HashMap::new()
        };
        
        let history = if let Ok(data) = fs::read_to_string("history_trades.json") {
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            Vec::new()
        };

        AppState {
            active_trades: trades,
            closed_trades: history,
            price_windows: HashMap::new(),
            config: cfg,
            is_running: false, // يبدأ متوقفاً بانتظار أوامرك
            waiting_for_amount: false,
            last_update_id: 0,
        }
    }

    fn analyze_tick(&mut self, symbol: String, price: f64) -> Option<TradeAction> {
        // الشرط الملكي: إذا لم تأمر بالتشغيل، لا نفعل شيئاً (ولكننا نراقب بصمت)
        if !self.is_running {
            return None;
        }

        let now = get_timestamp_secs();

        // 1. Check Sell (Trailing Stop)
        if let Some(trade) = self.active_trades.get_mut(&symbol) {
            if price > trade.peak_price {
                trade.peak_price = price;
            }
            
            let drawdown = (trade.peak_price - price) / trade.peak_price;
            if drawdown >= 0.03 { // 3% Trailing Stop
                let action = TradeAction::Sell { 
                    symbol: symbol.clone(), 
                    price, 
                    qty: trade.quantity, 
                    buy_price: trade.buy_price,
                };
                self.active_trades.remove(&symbol);
                return Some(action);
            }
            return None;
        }

        // 2. Check Buy (Pump Detection)
        let window = self.price_windows.entry(symbol.clone()).or_insert(VecDeque::new());
        window.push_back((now, price));

        while let Some(first) = window.front() {
            if now - first.0 > 30 { window.pop_front(); } else { break; }
        }

        if window.len() < 3 { return None; }

        let oldest_price = window.front().unwrap().1;
        if oldest_price == 0.0 { return None; } 
        
        let increase = (price - oldest_price) / oldest_price;

        if increase >= 0.05 { // 5% Pump
            self.price_windows.remove(&symbol); // Reset logic
            return Some(TradeAction::Buy { symbol, price });
        }
        
        None
    }
}

// --- Telegram Command Center (The Royal Interface) ---

async fn telegram_listener(state: Arc<Mutex<AppState>>, client: Client) {
    let token = {
        let lock = state.lock().await;
        lock.config.bot_token.clone()
    };
    
    loop {
        let offset = { state.lock().await.last_update_id + 1 };
        let url = format!("https://api.telegram.org/bot{}/getUpdates?offset={}&timeout=30", token, offset);
        
        if let Ok(resp) = client.get(&url).send().await {
            if let Ok(json) = resp.json::<Value>().await {
                if let Some(results) = json["result"].as_array() {
                    for update in results {
                        let update_id = update["update_id"].as_u64().unwrap_or(offset);
                        {
                            let mut lock = state.lock().await;
                            lock.last_update_id = update_id;
                        }

                        if let Some(message) = update.get("message") {
                            if let Some(text) = message["text"].as_str() {
                                let chat_id = message["chat"]["id"].as_i64().unwrap_or(0).to_string();
                                process_user_command(text, &chat_id, &state, &client).await;
                            }
                        }
                    }
                }
            }
        }
        sleep(Duration::from_millis(500)).await;
    }
}

async fn process_user_command(text: &str, chat_id: &str, state: &Arc<Mutex<AppState>>, client: &Client) {
    let mut lock = state.lock().await;
    
    // التحقق من هوية المرسل (أمان إضافي)
    if chat_id != lock.config.chat_id { return; }

    let config_clone = lock.config.clone(); // Clone for async use

    if lock.waiting_for_amount {
        if let Ok(amount) = text.parse::<f64>() {
            lock.config.trade_amount = amount;
            lock.waiting_for_amount = false;
            lock.is_running = true; // إطلاق الوحش
            
            let msg = format!("✅ **تم قبول الأمر يا سيدي.**\n\n💰 المبلغ المحدد للصفقة: **{:.2} USDT**\n🚀 **الحالة:** النظام يعمل الآن ويراقب السوق بكفاءة قصوى.", amount);
            drop(lock); // Unlock before sending network request
            send_telegram_direct(client, &config_clone, &msg).await;
            return;
        } else {
            let msg = "⚠️ **عذراً يا سيدي، الإدخال غير صحيح.**\nأرجو التكرم بإدخال رقم صحيح للمبلغ (مثال: 50 أو 100).";
            drop(lock);
            send_telegram_direct(client, &config_clone, msg).await;
            return;
        }
    }

    match text {
        "/start" => {
            let msg = "👑 **أهلاً بك يا سيد العالم في نظام OMEGA ROYAL** 👑\n\nأنا خادمك الرقمي المطيع، مبرمج لأخدم أهدافك المالية بدقة متناهية.\n\n📜 **قائمة الأوامر المتاحة لمقامك الرفيع:**\n\n🟢 `/run` - تشغيل النظام (سيتم سؤالك عن المبلغ).\n🔴 `/stop` - إيقاف النظام فوراً (وضع الأمان).\n📊 `/status` - عرض الصفقات المفتوحة حالياً.\n📑 `/report` - تقرير الأرباح والخسائر للصفقات المغلقة.\n\nبانتظار إشارتك يا سيدي.";
            drop(lock);
            send_telegram_direct(client, &config_clone, msg).await;
        },
        "/run" => {
            lock.waiting_for_amount = true;
            let msg = "💳 **تحت أمرك.**\n\nكم ترغب أن نخصص لكل صفقة يا سيدي؟ (أدخل الرقم فقط)";
            drop(lock);
            send_telegram_direct(client, &config_clone, msg).await;
        },
        "/stop" => {
            lock.is_running = false;
            lock.waiting_for_amount = false;
            let msg = "🛑 **تم تنفيذ الأمر.**\n\nتم إيقاف عمليات الشراء الجديدة. النظام في وضع السكون.";
            drop(lock);
            send_telegram_direct(client, &config_clone, msg).await;
        },
        "/status" => {
            let count = lock.active_trades.len();
            let mut report = format!("📊 **تقرير الحالة المباشر**\n\n🔹 الحالة: {}\n🔹 عدد الصفقات النشطة: {}\n\n", 
                if lock.is_running { "نشط 🟢" } else { "متوقف 🔴" }, count);
            
            for t in lock.active_trades.values() {
                report.push_str(&format!("▫️ {} | دخول: {:.4} | وقت: {}\n", t.symbol, t.buy_price, t.entry_time_str));
            }
            
            if count == 0 { report.push_str("لا يوجد صفقات نشطة حالياً يا سيدي."); }
            drop(lock);
            send_telegram_direct(client, &config_clone, &report).await;
        },
        "/report" => {
            let total_trades = lock.closed_trades.len();
            let mut total_pnl = 0.0;
            let mut wins = 0;
            
            for t in &lock.closed_trades {
                total_pnl += t.profit_usdt;
                if t.pnl_percent > 0.0 { wins += 1; }
            }
            
            let msg = format!("📑 **التقرير المالي (الأرشيف)**\n\n📌 إجمالي الصفقات: {}\n✅ الصفقات الرابحة: {}\n💰 صافي الربح/الخسارة: {:.2} USDT\n\nنحن نسعى دوماً لزيادة ثروتك يا سيدي.", total_trades, wins, total_pnl);
            drop(lock);
            send_telegram_direct(client, &config_clone, &msg).await;
        },
        _ => {
            // تجاهل أي نص آخر للحفاظ على الهيبة
        }
    }
}

// --- Trade Executor (The Worker) ---

async fn trade_executor(mut rx: mpsc::Receiver<TradeAction>, state: Arc<Mutex<AppState>>, client: Client) {
    while let Some(action) = rx.recv().await {
        let config = { state.lock().await.config.clone() };

        match action {
            TradeAction::Buy { symbol, price } => {
                // تنفيذ الشراء
                if place_order(&client, &config, &symbol, "BUY", None, Some(config.trade_amount)).await {
                    let estimated_qty = (config.trade_amount / price) * 0.998; 
                    
                    let trade = Trade {
                        symbol: symbol.clone(),
                        buy_price: price,
                        peak_price: price,
                        quantity: estimated_qty,
                        timestamp: get_timestamp_secs(),
                        entry_time_str: get_current_time_str(),
                    };

                    let mut lock = state.lock().await;
                    lock.active_trades.insert(symbol.clone(), trade);
                    save_active_trades(&lock);
                    
                    let msg = format!("🟢 **صفقة جديدة بأمر النظام**\n\n💎 العملة: **{}**\n💵 السعر: {}\n⏱ الوقت: {}", symbol, price, get_current_time_str());
                    drop(lock);
                    send_telegram_direct(&client, &config, &msg).await;
                }
            },
            TradeAction::Sell { symbol, price, qty, buy_price } => {
                // تنفيذ البيع
                if place_order(&client, &config, &symbol, "SELL", Some(qty), None).await {
                    let pnl_percent = (price - buy_price) / buy_price;
                    let profit_usdt = (price - buy_price) * qty;

                    let mut lock = state.lock().await;
                    
                    // تسجيل الصفقة في الأرشيف
                    let closed = ClosedTrade {
                        symbol: symbol.clone(),
                        pnl_percent,
                        profit_usdt,
                        close_time: get_current_time_str(),
                    };
                    lock.closed_trades.push(closed);
                    
                    // حفظ البيانات
                    save_history(&lock);
                    save_active_trades(&lock);
                    
                    let msg = format!("💰 **جني أرباح فاخر**\n\n💎 العملة: **{}**\n📈 الربح: {:.2}%\n💵 صافي الربح: {:.2} USDT\n\nاقتناص يليق بمقامك يا سيدي.", symbol, pnl_percent * 100.0, profit_usdt);
                    drop(lock);
                    send_telegram_direct(&client, &config, &msg).await;
                }
            }
        }
    }
}

// --- API Helpers ---

fn save_active_trades(state: &AppState) {
    if let Ok(json) = serde_json::to_string(&state.active_trades) {
        let _ = fs::write("active_trades.json", json);
    }
}

fn save_history(state: &AppState) {
    if let Ok(json) = serde_json::to_string(&state.closed_trades) {
        let _ = fs::write("history_trades.json", json);
    }
}

async fn send_telegram_direct(client: &Client, config: &Config, text: &str) {
    let url = format!("https://api.telegram.org/bot{}/sendMessage", config.bot_token);
    let params = [("chat_id", &config.chat_id), ("text", text), ("parse_mode", "Markdown")];
    let _ = client.post(&url).form(&params).send().await;
}

async fn place_order(client: &Client, config: &Config, symbol: &str, side: &str, qty: Option<f64>, quote_qty: Option<f64>) -> bool {
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64;
    let mut params = format!("symbol={}&side={}&type=MARKET&timestamp={}&recvWindow=5000", symbol, side, timestamp);

    if let Some(q) = quote_qty { params.push_str(&format!("&quoteOrderQty={}", q)); } 
    else if let Some(q) = qty { params.push_str(&format!("&quantity={:.4}", q)); }

    let signature = sign_query(&params, &config.api_secret);
    let url = format!("{}/api/v3/order?{}&signature={}", MEXC_BASE_URL, params, signature);

    let res = client.post(&url)
        .header("X-MEXC-APIKEY", &config.api_key)
        .header("Content-Type", "application/json")
        .send().await;

    match res {
        Ok(r) => r.status().is_success(),
        Err(_) => false,
    }
}

// --- WebSocket Handler (Hyper Speed) ---

async fn ws_handler(symbols: Vec<String>, state: Arc<Mutex<AppState>>, tx: mpsc::Sender<TradeAction>) {
    loop {
        let (ws_stream, _) = match connect_async(MEXC_WS_URL).await {
            Ok(s) => s,
            Err(_) => { sleep(Duration::from_secs(5)).await; continue; }
        };

        let (mut write, mut read) = ws_stream.split();
        let params = json!({
            "method": "SUBSCRIPTION",
            "params": symbols.iter().map(|s| format!("spot@public.deals.v3.api@{}", s)).collect::<Vec<_>>()
        });

        if write.send(Message::Text(params.to_string())).await.is_err() { continue; }

        while let Some(msg) = read.next().await {
            if let Ok(Message::Text(text)) = msg {
                if let Ok(parsed) = serde_json::from_str::<Value>(&text) {
                    if let Some(deals) = parsed.get("d").and_then(|d| d.get("deals")) {
                        if let Some(arr) = deals.as_array() {
                            let symbol = parsed["s"].as_str().unwrap_or_default().to_string();
                            for deal in arr {
                                if let Some(p_str) = deal["p"].as_str() {
                                    if let Ok(price) = p_str.parse::<f64>() {
                                        let action = {
                                            // Lock is extremely short-lived for speed
                                            let mut lock = state.lock().await;
                                            lock.analyze_tick(symbol.clone(), price)
                                        };
                                        if let Some(act) = action {
                                            let _ = tx.send(act).await;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        sleep(Duration::from_secs(1)).await;
    }
}

// --- Main Entry ---

#[tokio::main]
async fn main() {
    dotenv().ok();
    
    // Load Env Vars
    let token = env::var("TELEGRAM_BOT_TOKEN").expect("Token");
    let chat_id = env::var("TELEGRAM_CHAT_ID").expect("ChatID");
    let api_key = env::var("MEXC_API_KEY").expect("Key");
    let secret = env::var("MEXC_API_SECRET").expect("Secret");
    
    // config initialization
    let config = Config {
        api_key, api_secret: secret, bot_token: token, chat_id,
        trade_amount: 0.0, // Default 0, waiting for user input
    };

    println!("👑 OMEGA ROYAL SYSTEM INITIALIZING...");
    
    let state = Arc::new(Mutex::new(AppState::new(config)));
    let (tx, rx) = mpsc::channel::<TradeAction>(100);

    // 1. تشغيل متلقي الأوامر من تليجرام (Command Center)
    let state_telegram = state.clone();
    tokio::spawn(async move {
        telegram_listener(state_telegram, Client::new()).await;
    });

    // 2. تشغيل منفذ الصفقات (Executor)
    let state_executor = state.clone();
    tokio::spawn(async move {
        trade_executor(rx, state_executor, Client::new()).await;
    });

    // 3. جلب العملات
    let client = Client::new();
    let resp = client.get(format!("{}/api/v3/exchangeInfo", MEXC_BASE_URL)).send().await;
    let mut symbols: Vec<String> = Vec::new();
    if let Ok(r) = resp {
        if let Ok(json) = r.json::<Value>().await {
             if let Some(list) = json["symbols"].as_array() {
                 for s in list {
                     let name = s["symbol"].as_str().unwrap_or_default();
                     let status = s["status"].as_str().unwrap_or("DISABLED");
                     if name.ends_with("USDT") && status == "ENABLED" && 
                        !name.contains("3L") && !name.contains("3S") && !name.contains("DOWN") {
                         symbols.push(name.to_string());
                     }
                 }
             }
        }
    }

    println!("✅ All Assets Loaded: {}", symbols.len());
    
    // 4. إرسال رسالة الترحيب عند التشغيل
    {
        let lock = state.lock().await;
        let c = lock.config.clone();
        drop(lock);
        send_telegram_direct(&client, &c, "🤖 **تم تشغيل الخادم بنجاح.**\nأرسل /start لعرض قائمة الأوامر الملكية.").await;
    }

    // 5. إطلاق شبكة المراقبة (Shards)
    let mut handles = vec![];
    for chunk in symbols.chunks(SYMBOLS_PER_SOCKET) {
        let chunk_vec = chunk.to_vec();
        let state_clone = state.clone();
        let tx_clone = tx.clone();
        handles.push(tokio::spawn(async move {
            ws_handler(chunk_vec, state_clone, tx_clone).await;
        }));
        sleep(Duration::from_millis(100)).await;
    }

    futures_util::future::join_all(handles).await;
}