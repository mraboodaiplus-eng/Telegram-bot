use std::collections::{HashMap, VecDeque};
use std::env;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{Mutex, mpsc};
use tokio::time::sleep;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::json; // Removed generic Value to optimize speed
use futures_util::{StreamExt, SinkExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use dotenv::dotenv;
use std::fs;
use chrono::{DateTime, Utc};
use warp::Filter;

// 🚀 JEMALLOC: ذاكرة الفيسبوك السريعة
#[global_allocator]
static ALLOC: jemallocator::Jemalloc = jemallocator::Jemalloc;

// --- Config Constants ---
const MEXC_BASE_URL: &str = "https://api.mexc.com";
const MEXC_WS_URL: &str = "wss://wbs.mexc.com/ws";
const SYMBOLS_PER_SOCKET: usize = 30;

// --- ⚡ SPEED STRUCTURES (Zero-Cost Deserialization) ⚡ ---
// استبدلنا تحليل JSON العام بهياكل محددة لتسريع المعالجة
#[derive(Deserialize)]
struct WsMessage {
    s: String, // Symbol
    d: WsData, // Data
}

#[derive(Deserialize)]
struct WsData {
    deals: Vec<WsDeal>,
}

#[derive(Deserialize)]
struct WsDeal {
    p: String, // Price comes as string
    // t: u64, // Time (ignored for speed)
    // S: i32, // Type (ignored for speed)
}

// --- Regular Structures ---
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
    closed_trades: Vec<ClosedTrade>,
    price_windows: HashMap<String, VecDeque<(u64, f64)>>, 
    config: Config,
    is_running: bool,
    waiting_for_amount: bool,
    last_update_id: u64,
}

#[derive(Clone)]
struct Config {
    api_key: String,
    api_secret: String,
    bot_token: String,
    chat_id: String,
    trade_amount: f64,
}

// --- Helper Functions ---
#[inline(always)] // تعليمات للمترجم بدمج الكود للسرعة
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

// --- DUMMY SERVER ---
async fn start_health_server() {
    let port_str = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let port: u16 = port_str.parse().unwrap_or(8080);
    let route = warp::any().map(|| "⚡ OMEGA ROYAL: HFT MODE ACTIVE");
    warp::serve(route).run(([0, 0, 0, 0], port)).await;
}

// --- Core Logic ---
impl AppState {
    fn new(cfg: Config) -> Self {
        AppState {
            active_trades: HashMap::new(),
            closed_trades: Vec::new(),
            price_windows: HashMap::new(),
            config: cfg,
            is_running: false,
            waiting_for_amount: false,
            last_update_id: 0,
        }
    }

    // ⚡⚡ ULTRA-LOW LATENCY ANALYZER ⚡⚡
    #[inline(always)]
    fn analyze_tick(&mut self, symbol: &str, price: f64) -> Option<TradeAction> {
        if !self.is_running { return None; }

        let now = get_timestamp_secs();

        // 1. Sell Logic
        if let Some(trade) = self.active_trades.get_mut(symbol) {
            if price > trade.peak_price { trade.peak_price = price; }
            let drawdown = (trade.peak_price - price) / trade.peak_price;
            
            if drawdown >= 0.03 {
                let action = TradeAction::Sell { 
                    symbol: symbol.to_string(), price, qty: trade.quantity, buy_price: trade.buy_price 
                };
                self.active_trades.remove(symbol);
                return Some(action);
            }
            return None;
        }

        // 2. Buy Logic
        let window = self.price_windows.entry(symbol.to_string()).or_insert_with(|| VecDeque::with_capacity(50));
        window.push_back((now, price));
        
        // Fast Pruning loop
        while let Some(first) = window.front() {
            if now - first.0 > 30 { window.pop_front(); } else { break; }
        }
        
        if window.len() < 3 { return None; }

        // Unsafe unwrap skipped because we checked len >= 3
        let oldest_price = window.front().unwrap().1;
        
        if oldest_price <= 0.00000001 { return None; } // avoid div by zero
        let increase = (price - oldest_price) / oldest_price;

        if increase >= 0.05 {
            self.price_windows.remove(symbol);
            return Some(TradeAction::Buy { symbol: symbol.to_string(), price });
        }
        None
    }
}

// --- Network & Execution ---
async fn place_order(client: &Client, config: &Config, symbol: &str, side: &str, qty: Option<f64>, quote_qty: Option<f64>) -> bool {
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64;
    let mut params = format!("symbol={}&side={}&type=MARKET&timestamp={}&recvWindow=5000", symbol, side, timestamp);
    if let Some(q) = quote_qty { params.push_str(&format!("&quoteOrderQty={}", q)); } 
    else if let Some(q) = qty { params.push_str(&format!("&quantity={:.4}", q)); }
    
    let signature = sign_query(&params, &config.api_secret);
    let url = format!("{}/api/v3/order?{}&signature={}", MEXC_BASE_URL, params, signature);
    
    // Client is reused, keeping TCP connection alive (Keep-Alive)
    let res = client.post(&url)
        .header("X-MEXC-APIKEY", &config.api_key)
        .header("Content-Type", "application/json")
        .send().await;

    match res { Ok(r) => r.status().is_success(), Err(_) => false }
}

async fn telegram_listener(state: Arc<Mutex<AppState>>, client: Client) {
    let token = { state.lock().await.config.bot_token.clone() };
    loop {
        let offset = { state.lock().await.last_update_id + 1 };
        let url = format!("https://api.telegram.org/bot{}/getUpdates?offset={}&timeout=30", token, offset);
        if let Ok(resp) = client.get(&url).send().await {
            // Using generic Value here is fine, speed is not critical for Telegram
            if let Ok(json) = resp.json::<serde_json::Value>().await {
                if let Some(results) = json["result"].as_array() {
                    for update in results {
                        let update_id = update["update_id"].as_u64().unwrap_or(offset);
                        { state.lock().await.last_update_id = update_id; }
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
        sleep(Duration::from_millis(200)).await;
    }
}

async fn process_user_command(text: &str, chat_id: &str, state: &Arc<Mutex<AppState>>, client: &Client) {
    let mut lock = state.lock().await;
    if chat_id != lock.config.chat_id { return; }
    let config_clone = lock.config.clone();

    if lock.waiting_for_amount {
        if let Ok(amount) = text.parse::<f64>() {
            lock.config.trade_amount = amount;
            lock.waiting_for_amount = false;
            lock.is_running = true;
            let msg = format!("✅ **HFT PROTOCOL ENGAGED.**\n💰 Alloc: **{:.2} USDT**", amount);
            drop(lock);
            send_telegram_direct(client, &config_clone, &msg).await;
            return;
        } else {
            drop(lock);
            send_telegram_direct(client, &config_clone, "⚠️ Invalid Amount.").await;
            return;
        }
    }

    match text {
        "/start" => {
            let msg = "👑 **OMEGA ROYAL: HFT EDITION**\n\n🟢 `/run`\n🔴 `/stop`\n📊 `/status`\n📑 `/report`";
            drop(lock);
            send_telegram_direct(client, &config_clone, msg).await;
        },
        "/run" => {
            lock.waiting_for_amount = true;
            drop(lock);
            send_telegram_direct(client, &config_clone, "💳 Amount (USDT):").await;
        },
        "/stop" => {
            lock.is_running = false;
            drop(lock);
            send_telegram_direct(client, &config_clone, "🛑 Halted.").await;
        },
        "/status" => {
            let count = lock.active_trades.len();
            let mut report = format!("📊 **STATUS**\nState: {}\nActive: {}\n", 
                if lock.is_running { "ON" } else { "OFF" }, count);
            for t in lock.active_trades.values() {
                report.push_str(&format!("▫️ {} | {:.4}\n", t.symbol, t.buy_price));
            }
            drop(lock);
            send_telegram_direct(client, &config_clone, &report).await;
        },
        "/report" => {
            let mut total_pnl = 0.0;
            for t in &lock.closed_trades { total_pnl += t.profit_usdt; }
            let msg = format!("📑 **REPORT**\n💰 Net PNL: {:.2} USDT", total_pnl);
            drop(lock);
            send_telegram_direct(client, &config_clone, &msg).await;
        },
        _ => {}
    }
}

async fn send_telegram_direct(client: &Client, config: &Config, text: &str) {
    let url = format!("https://api.telegram.org/bot{}/sendMessage", config.bot_token);
    let params = [("chat_id", config.chat_id.as_str()), ("text", text), ("parse_mode", "Markdown")];
    let _ = client.post(&url).form(&params).send().await;
}

async fn trade_executor(mut rx: mpsc::Receiver<TradeAction>, state: Arc<Mutex<AppState>>, client: Client) {
    while let Some(action) = rx.recv().await {
        // Fast clone config outside match
        let config = { state.lock().await.config.clone() };
        
        match action {
            TradeAction::Buy { symbol, price } => {
                if place_order(&client, &config, &symbol, "BUY", None, Some(config.trade_amount)).await {
                    let estimated_qty = (config.trade_amount / price) * 0.998; 
                    let trade = Trade {
                        symbol: symbol.clone(), buy_price: price, peak_price: price, 
                        quantity: estimated_qty, timestamp: get_timestamp_secs(), 
                        entry_time_str: get_current_time_str(),
                    };
                    
                    let mut lock = state.lock().await;
                    lock.active_trades.insert(symbol.clone(), trade);
                    drop(lock); // Release lock immediately
                    
                    let msg = format!("🟢 **BUY** {} @ {}", symbol, price);
                    send_telegram_direct(&client, &config, &msg).await;
                }
            },
            TradeAction::Sell { symbol, price, qty, buy_price } => {
                if place_order(&client, &config, &symbol, "SELL", Some(qty), None).await {
                    let pnl = (price - buy_price) * qty;
                    let mut lock = state.lock().await;
                    lock.closed_trades.push(ClosedTrade { 
                        symbol: symbol.clone(), pnl_percent: (price-buy_price)/buy_price, 
                        profit_usdt: pnl, close_time: get_current_time_str() 
                    });
                    drop(lock); // Release lock immediately
                    
                    let msg = format!("💰 **SELL** {} | PNL: {:.2}", symbol, pnl);
                    send_telegram_direct(&client, &config, &msg).await;
                }
            }
        }
    }
}

async fn ws_handler(symbols: Vec<String>, state: Arc<Mutex<AppState>>, tx: mpsc::Sender<TradeAction>) {
    loop {
        let (ws_stream, _) = match connect_async(MEXC_WS_URL).await { Ok(s) => s, Err(_) => { sleep(Duration::from_secs(2)).await; continue; } };
        let (mut write, mut read) = ws_stream.split();
        let params = json!({ "method": "SUBSCRIPTION", "params": symbols.iter().map(|s| format!("spot@public.deals.v3.api@{}", s)).collect::<Vec<_>>() });
        if write.send(Message::Text(params.to_string())).await.is_err() { continue; }
        
        while let Some(msg) = read.next().await {
            if let Ok(Message::Text(text)) = msg {
                // ⚡⚡ OPTIMIZATION #3: TYPED DESERIALIZATION ⚡⚡
                // This replaces the slow 'Value' parsing with fast struct parsing
                if let Ok(parsed) = serde_json::from_str::<WsMessage>(&text) {
                    let symbol = parsed.s; // Direct access, no unwrap needed
                    for deal in parsed.d.deals {
                        // Fast string-to-float parse
                        if let Ok(price) = deal.p.parse::<f64>() {
                            
                            // ⚡⚡ OPTIMIZATION #2: HYPER-SPEED MUTEX ⚡⚡
                            // Calculate ONLY what we need inside the lock, then drop it.
                            let action = {
                                let mut lock = state.lock().await;
                                lock.analyze_tick(&symbol, price)
                            }; // Lock is dropped HERE automatically

                            // Send action to executor (outside the lock)
                            if let Some(act) = action { 
                                let _ = tx.send(act).await; 
                            }
                        }
                    }
                }
            }
        }
        sleep(Duration::from_secs(1)).await;
    }
}

#[tokio::main]
async fn main() {
    // ⚡⚡ OPTIMIZATION #4: EXECUTION KEEP-ALIVE ⚡⚡
    // Connection pooling configured for maximum stickiness
    let client = Client::builder()
        .tcp_nodelay(true) // Disable Nagle's alg (Low Latency)
        .pool_idle_timeout(Duration::from_secs(300)) // Keep connections open for 5 mins
        .pool_max_idle_per_host(50) // Allow many idle connections ready to fire
        .build()
        .expect("Client build failed");

    let token = env::var("TELEGRAM_BOT_TOKEN").expect("Token");
    let chat_id = env::var("TELEGRAM_CHAT_ID").expect("ChatID");
    let api_key = env::var("MEXC_API_KEY").expect("Key");
    let secret = env::var("MEXC_API_SECRET").expect("Secret");

    tokio::spawn(async move { start_health_server().await; });

    let config = Config { api_key, api_secret: secret, bot_token: token, chat_id, trade_amount: 0.0 };
    println!("👑 OMEGA ROYAL ENGINE: HFT MODE ACTIVATED");
    
    let state = Arc::new(Mutex::new(AppState::new(config)));
    let (tx, rx) = mpsc::channel::<TradeAction>(500); // Increased buffer

    let state_telegram = state.clone();
    let client_telegram = client.clone();
    tokio::spawn(async move { telegram_listener(state_telegram, client_telegram).await; });

    let state_executor = state.clone();
    let client_executor = client.clone();
    tokio::spawn(async move { trade_executor(rx, state_executor, client_executor).await; });

    // Initial Info Fetch
    let resp = client.get(format!("{}/api/v3/exchangeInfo", MEXC_BASE_URL)).send().await;
    let mut symbols: Vec<String> = Vec::new();
    if let Ok(r) = resp {
        // We still use Value here because it runs once and the schema is complex
        if let Ok(json) = r.json::<serde_json::Value>().await {
             if let Some(list) = json["symbols"].as_array() {
                 for s in list {
                     let name = s["symbol"].as_str().unwrap_or_default();
                     if name.ends_with("USDT") && s["status"].as_str().unwrap_or("") == "ENABLED" 
                        && !name.contains("3L") && !name.contains("DOWN") {
                         symbols.push(name.to_string());
                     }
                 }
             }
        }
    }
    println!("✅ LOADED {} PAIRS.", symbols.len());
    
    // Notify Admin
    {
        let lock = state.lock().await;
        let c = lock.config.clone();
        drop(lock);
        send_telegram_direct(&client, &c, "🤖 **SYSTEM OPTIMIZED: HFT SPEC (STRANGER'S ORDERS EXECUTED).**").await;
    }

    let mut handles = vec![];
    for chunk in symbols.chunks(SYMBOLS_PER_SOCKET) {
        let chunk_vec = chunk.to_vec();
        let state_clone = state.clone();
        let tx_clone = tx.clone();
        handles.push(tokio::spawn(async move { ws_handler(chunk_vec, state_clone, tx_clone).await; }));
        sleep(Duration::from_millis(20)).await; // Shorter stagger
    }
    futures_util::future::join_all(handles).await;
}