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

    // AI settings
    #[serde(default = "default_ai_mode")]
    ai_mode: String, // "claude-cli" | "claude-api" | "codex-cli" | "openai-api"
    #[serde(default)]
    anthropic_api_key: String,
    #[serde(default)]
    openai_api_key: String,
    #[serde(default = "default_claude_model")]
    claude_model: String,
    #[serde(default = "default_openai_model")]
    openai_model: String,
}

fn default_theme() -> String {
    "system".to_string()
}

fn default_ai_mode() -> String {
    "claude-cli".to_string()
}

fn default_claude_model() -> String {
    "sonnet".to_string()
}

fn default_openai_model() -> String {
    "gpt-4o".to_string()
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
fn set_config(
    server_url: String,
    theme: Option<String>,
    ai_mode: Option<String>,
    anthropic_api_key: Option<String>,
    openai_api_key: Option<String>,
    claude_model: Option<String>,
    openai_model: Option<String>,
) -> Result<(), String> {
    let existing = read_config_raw();
    let cfg = Config {
        server_url,
        theme: theme.unwrap_or(existing.theme),
        window_width: existing.window_width,
        window_height: existing.window_height,
        ai_mode: ai_mode.unwrap_or(existing.ai_mode),
        anthropic_api_key: anthropic_api_key.unwrap_or(existing.anthropic_api_key),
        openai_api_key: openai_api_key.unwrap_or(existing.openai_api_key),
        claude_model: claude_model.unwrap_or(existing.claude_model),
        openai_model: openai_model.unwrap_or(existing.openai_model),
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

// -------- AI dispatcher --------

async fn call_claude_cli(system_prompt: &str, user_prompt: &str, model: &str) -> Result<String, String> {
    let full_prompt = format!("{}\n\n{}", system_prompt, user_prompt);
    let model = model.to_string();
    let result = tokio::task::spawn_blocking(move || {
        std::process::Command::new("claude")
            .args(["-p", &full_prompt, "--model", &model, "--output-format", "text"])
            .output()
    })
    .await
    .map_err(|e| format!("task join: {}", e))?;

    let output = result.map_err(|e| format!("spawn claude: {}", e))?;
    if !output.status.success() {
        return Err(format!("claude CLI error: {}", String::from_utf8_lossy(&output.stderr)));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

async fn call_claude_api(
    client: &reqwest::Client,
    system_prompt: &str,
    user_prompt: &str,
    api_key: &str,
    model: &str,
) -> Result<String, String> {
    if api_key.is_empty() {
        return Err("API key Anthropic mancante".into());
    }
    // Mappa short names al model id completo quando necessario
    let model_id = match model {
        "sonnet" => "claude-sonnet-4-5-20250929",
        "opus" => "claude-opus-4-5-20250929",
        "haiku" => "claude-haiku-4-5-20251001",
        m => m,
    };
    let body = serde_json::json!({
        "model": model_id,
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": [ { "role": "user", "content": user_prompt } ]
    });
    let resp = client
        .post("https://api.anthropic.com/v1/messages")
        .header("x-api-key", api_key)
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("claude API: {}", e))?;
    let json: serde_json::Value = resp.json().await.map_err(|e| format!("parse JSON: {}", e))?;
    json["content"][0]["text"]
        .as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| format!("risposta inattesa: {}", json))
}

async fn call_codex_cli(system_prompt: &str, user_prompt: &str, model: &str) -> Result<String, String> {
    let full_prompt = format!("{}\n\n{}", system_prompt, user_prompt);
    let model = model.to_string();
    let result = tokio::task::spawn_blocking(move || {
        std::process::Command::new("codex")
            .args(["exec", "--skip-git-repo-check", "-m", &model, &full_prompt])
            .output()
    })
    .await
    .map_err(|e| format!("task join: {}", e))?;

    let output = result.map_err(|e| format!("spawn codex: {}", e))?;
    if !output.status.success() {
        return Err(format!("codex CLI error: {}", String::from_utf8_lossy(&output.stderr)));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

async fn call_openai_api(
    client: &reqwest::Client,
    system_prompt: &str,
    user_prompt: &str,
    api_key: &str,
    model: &str,
) -> Result<String, String> {
    if api_key.is_empty() {
        return Err("API key OpenAI mancante".into());
    }
    let body = serde_json::json!({
        "model": model,
        "max_tokens": 2048,
        "messages": [
            { "role": "system", "content": system_prompt },
            { "role": "user", "content": user_prompt }
        ]
    });
    let resp = client
        .post("https://api.openai.com/v1/chat/completions")
        .header("Authorization", format!("Bearer {}", api_key))
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("openai: {}", e))?;
    let json: serde_json::Value = resp.json().await.map_err(|e| format!("parse JSON: {}", e))?;
    json["choices"][0]["message"]["content"]
        .as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| format!("risposta inattesa: {}", json))
}

async fn call_ai(cfg: &Config, system_prompt: &str, user_prompt: &str) -> Result<String, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .map_err(|e| e.to_string())?;
    match cfg.ai_mode.as_str() {
        "claude-cli" | "cli" => call_claude_cli(system_prompt, user_prompt, &cfg.claude_model).await,
        "claude-api" | "api" => call_claude_api(&client, system_prompt, user_prompt, &cfg.anthropic_api_key, &cfg.claude_model).await,
        "codex-cli" => call_codex_cli(system_prompt, user_prompt, &cfg.openai_model).await,
        "openai-api" => call_openai_api(&client, system_prompt, user_prompt, &cfg.openai_api_key, &cfg.openai_model).await,
        other => Err(format!("modalità AI sconosciuta: {}", other)),
    }
}

fn extract_json_object(text: &str) -> &str {
    let trimmed = text.trim();
    if let Some(start) = trimmed.find('{') {
        if let Some(end) = trimmed.rfind('}') {
            return &trimmed[start..=end];
        }
    }
    trimmed
}

#[derive(Debug, Serialize, Deserialize)]
struct SuggestResult {
    existing: Vec<String>,
    new: Vec<String>,
    raw: Option<String>,
}

#[tauri::command]
async fn suggest_tags(description: String, amount: f64, existing_tags: Vec<String>) -> Result<SuggestResult, String> {
    let cfg = read_config_raw();

    let existing_list = if existing_tags.is_empty() {
        "(nessuno)".to_string()
    } else {
        existing_tags.join(", ")
    };

    let system_prompt = "Sei un assistente che aiuta a classificare movimenti bancari italiani (Fineco). \
Rispondi SEMPRE e SOLO con un oggetto JSON valido, senza testo aggiuntivo, senza markdown code fences. \
Schema: {\"existing\": [\"tag1\", ...], \"new\": [\"tag2\", ...]}. \
- \"existing\": tag dell'elenco fornito pertinenti al movimento (0-3). \
- \"new\": 1-2 nuovi tag specifici e descrittivi del movimento, SEMPRE popolato se la descrizione permette una classificazione sensata, anche se \"existing\" contiene già suggerimenti. \
I nuovi tag devono essere più specifici/descrittivi dei generici: es. per una compravendita immobiliare preferisci 'immobile' a 'bonifico-in'; per un pagamento al supermercato 'conad' o 'supermercato' a 'spesa-generica'. \
I tag sono brevi (1-2 parole), minuscoli, senza accenti, es: 'spesa', 'ristorante', 'trasporti', 'immobile', 'stipendio'. \
Restituisci entrambe le liste vuote solo se la descrizione è davvero generica o incomprensibile.";

    let sign = if amount >= 0.0 { "entrata" } else { "uscita" };
    let user_prompt = format!(
        "Tag esistenti: {}\n\nMovimento ({}, {:.2}€):\n{}\n\nRispondi solo con JSON.",
        existing_list, sign, amount, description
    );

    let response = call_ai(&cfg, system_prompt, &user_prompt).await?;
    let json_str = extract_json_object(&response);

    match serde_json::from_str::<serde_json::Value>(json_str) {
        Ok(v) => {
            let existing = v["existing"]
                .as_array()
                .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default();
            let new_tags = v["new"]
                .as_array()
                .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default();
            Ok(SuggestResult { existing, new: new_tags, raw: None })
        }
        Err(e) => Err(format!("Risposta AI non parsabile ({}): {}", e, response)),
    }
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
        .invoke_handler(tauri::generate_handler![get_config, set_config, save_window_size, suggest_tags])
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
