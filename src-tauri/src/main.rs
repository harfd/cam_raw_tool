#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::{io::{BufRead, BufReader}, process::{Child, Command, Stdio}, sync::Mutex, time::Duration};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Clone, Serialize, Deserialize)]
struct Connection { url: String, token: String }
struct Backend { connection: Connection, child: Mutex<Child> }

#[tauri::command]
fn backend_connection(state: tauri::State<Backend>) -> Connection { state.connection.clone() }

#[tauri::command]
async fn save_xmp(app: tauri::AppHandle, contents: String, name: String) -> Result<bool, String> {
    if contents.len() > 33_554_432 { return Err("导出内容超过 32 MB，请减少选区或简化边界".into()); }
    let chosen = app.dialog().file().add_filter("Camera Raw 预设", &["xmp"]).set_file_name(&name).blocking_save_file();
    if let Some(path) = chosen {
        let path = path.into_path().map_err(|_| "无法读取保存位置")?;
        std::fs::write(path, contents.as_bytes()).map_err(|_| "无法写入文件，请选择其他保存位置")?;
        Ok(true)
    } else { Ok(false) }
}

fn start_backend(app: &tauri::App) -> Result<Backend, Box<dyn std::error::Error>> {
    let mut command;
    if cfg!(debug_assertions) {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_owned();
        command = Command::new(root.join(".venv/Scripts/python.exe"));
        command.current_dir(&root).args(["-m", "backend.server"]);
    } else {
        command = Command::new(app.path().resource_dir()?.join("server/raw-studio-server.exe"));
    }
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn()?;
    let stdout = child.stdout.take().ok_or("无法读取后端启动信息")?;
    let (sender, receiver) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
        let _ = sender.send(result);
    });
    let result = (|| -> Result<Connection, Box<dyn std::error::Error>> {
        let line = receiver.recv_timeout(Duration::from_secs(60))??;
        Ok(serde_json::from_str(&line)?)
    })();
    match result {
        Ok(connection) => Ok(Backend { connection, child: Mutex::new(child) }),
        Err(error) => { let _ = child.kill(); let _ = child.wait(); Err(error) }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| { let backend = start_backend(app)?; app.manage(backend); Ok(()) })
        .invoke_handler(tauri::generate_handler![backend_connection, save_xmp])
        .build(tauri::generate_context!()).expect("AI RAW Studio 启动失败");
    app.run(|app, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app.try_state::<Backend>() {
                if let Ok(mut child) = state.child.lock() { let _ = child.kill(); let _ = child.wait(); }
            }
        }
    });
}
