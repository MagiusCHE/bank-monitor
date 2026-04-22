use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
struct Config {
    #[serde(default)]
    server_url: String,
    #[serde(default = "default_theme")]
    theme: String,
    #[serde(default)]
    window_width: Option<f64>,
    #[serde(default)]
    window_height: Option<f64>,
}

fn default_theme() -> String {
    "system".to_string()
}

fn config_dir() -> PathBuf {
    let dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("bank-monitor");
    fs::create_dir_all(&dir).ok();
    dir
}

fn config_path() -> PathBuf {
    config_dir().join("config.json")
}

fn read_config_raw() -> Config {
    let path = config_path();
    if !path.exists() {
        return Config::default();
    }
    fs::read_to_string(&path)
        .ok()
        .and_then(|d| serde_json::from_str(&d).ok())
        .unwrap_or_default()
}

#[tauri::command]
fn get_config() -> Result<Config, String> {
    Ok(read_config_raw())
}

#[tauri::command]
fn set_config(server_url: String, theme: Option<String>) -> Result<(), String> {
    let existing = read_config_raw();
    let cfg = Config {
        server_url,
        theme: theme.unwrap_or(existing.theme),
        window_width: existing.window_width,
        window_height: existing.window_height,
    };
    let data = serde_json::to_string_pretty(&cfg).map_err(|e| e.to_string())?;
    fs::write(config_path(), data).map_err(|e| e.to_string())
}

#[tauri::command]
fn save_window_size(width: f64, height: f64) -> Result<(), String> {
    let mut cfg = read_config_raw();
    cfg.window_width = Some(width);
    cfg.window_height = Some(height);
    let data = serde_json::to_string_pretty(&cfg).map_err(|e| e.to_string())?;
    fs::write(config_path(), data).map_err(|e| e.to_string())
}

// Delta tra inner_size() letto e inner_size() impostato nel builder.
// Su Wayland con CSD, inner_size() include le decorazioni.
static CSD_DELTA: Mutex<Option<(f64, f64)>> = Mutex::new(None);

// Contatore monotono per debounce del resize
static RESIZE_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

// Ultima dimensione fisica vista, per filtrare resize duplicati
static LAST_SEEN_SIZE: Mutex<(u32, u32)> = Mutex::new((0, 0));

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(not(target_os = "android"))]
    let ready = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    #[cfg(not(target_os = "android"))]
    let ready_clone = ready.clone();

    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_http::init())
        .invoke_handler(tauri::generate_handler![get_config, set_config, save_window_size])
        .setup(move |app| {
            #[cfg(not(target_os = "android"))]
            {
                let cfg = read_config_raw();
                let w = cfg.window_width.filter(|v| *v > 100.0).unwrap_or(1100.0);
                let h = cfg.window_height.filter(|v| *v > 100.0).unwrap_or(750.0);

                eprintln!("[bank-monitor] setup: creating window {}x{}", w, h);

                let win = tauri::WebviewWindowBuilder::new(
                    app,
                    "main",
                    tauri::WebviewUrl::App("index.html".into()),
                )
                .title("Bank Monitor")
                .inner_size(w, h)
                .resizable(true)
                .center()
                .build()
                .map_err(|e: tauri::Error| e.to_string())?;

                // Calcola il delta CSD dopo un breve delay
                let ready_flag = ready.clone();
                let win_clone = win.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_millis(300));
                    if let Ok(inner) = win_clone.inner_size() {
                        if let Ok(sf) = win_clone.scale_factor() {
                            let actual_w = inner.width as f64 / sf;
                            let actual_h = inner.height as f64 / sf;
                            let dw = actual_w - w;
                            let dh = actual_h - h;
                            eprintln!(
                                "[bank-monitor] CSD delta: dw={}, dh={} (requested {}x{}, got {}x{})",
                                dw, dh, w, h, actual_w, actual_h
                            );
                            if let Ok(mut delta) = CSD_DELTA.lock() {
                                *delta = Some((dw, dh));
                            }
                            if let Ok(mut last) = LAST_SEEN_SIZE.lock() {
                                *last = (inner.width, inner.height);
                            }
                        }
                    }
                    ready_flag.store(true, std::sync::atomic::Ordering::Relaxed);
                });
            }

            #[cfg(target_os = "android")]
            {
                tauri::WebviewWindowBuilder::new(
                    app,
                    "main",
                    tauri::WebviewUrl::App("index.html".into()),
                )
                .build()
                .map_err(|e: tauri::Error| e.to_string())?;
            }

            Ok(())
        });

    #[cfg(not(target_os = "android"))]
    {
        builder = builder.on_window_event(move |window, event| {
            if let tauri::WindowEvent::Resized(size) = event {
                if !ready_clone.load(std::sync::atomic::Ordering::Relaxed) {
                    return;
                }

                let new_size = (size.width, size.height);
                {
                    let mut last = LAST_SEEN_SIZE.lock().unwrap();
                    if *last == new_size {
                        return;
                    }
                    *last = new_size;
                }

                let my_id = RESIZE_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
                let win = window.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(1));
                    let current = RESIZE_COUNTER.load(std::sync::atomic::Ordering::Relaxed);
                    if current != my_id {
                        return;
                    }

                    if let Ok(inner) = win.inner_size() {
                        if let Ok(sf) = win.scale_factor() {
                            let raw_w = inner.width as f64 / sf;
                            let raw_h = inner.height as f64 / sf;

                            let (dw, dh) = CSD_DELTA.lock().ok()
                                .and_then(|d| *d)
                                .unwrap_or((0.0, 0.0));
                            let w = raw_w - dw;
                            let h = raw_h - dh;

                            eprintln!("[bank-monitor] resize save: {:.0}x{:.0}", w, h);

                            if w > 100.0 && h > 100.0 {
                                let _ = save_window_size(w, h);
                            }
                        }
                    }
                });
            }
        });
    }

    builder
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
