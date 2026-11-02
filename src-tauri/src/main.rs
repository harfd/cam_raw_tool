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
async fn save_film(app: tauri::AppHandle, state: tauri::State<'_, Backend>, job_id: String, operation: String, name: String) -> Result<bool, String> {
    for id in [&job_id, &operation] {
        if id.len() != 32 || !id.bytes().all(|b| b.is_ascii_hexdigit()) { return Err("胶片任务编号无效".into()); }
    }
    let extension = if name.ends_with(".tif") { "tif" } else if name.ends_with(".jpg") { "jpg" } else { return Err("成片格式无效".into()); };
    let connection = state.connection.clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<bool, String> {
        let chosen = app.dialog().file().add_filter("胶片成片", &[extension]).set_file_name(if extension=="tif" {"胶片成片.tif"} else {"胶片成片.jpg"}).blocking_save_file();
        let Some(path) = chosen else { return Ok(false); };
        let mut path = path.into_path().map_err(|_| "无法读取保存位置")?;
        if path.extension().is_none() { path.set_extension(extension); }
        if path.extension().and_then(|x|x.to_str()).map(|x|x.to_lowercase()) != Some(extension.into()) { return Err("请选择与成片格式一致的文件扩展名".into()); }
        let temporary = path.with_extension(format!("{}.{}.tmp", extension, operation));
        let result = (|| -> Result<(), String> {
            let client = reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_secs(120)).build().map_err(|_| "无法连接成片服务")?;
            let mut response = client.get(format!("{}/api/jobs/{}/film/{}/download",connection.url,job_id,operation)).bearer_auth(&connection.token).send().map_err(|_| "读取成片失败，请重试")?.error_for_status().map_err(|_| "成片不存在或尚未完成")?;
            let mut file = std::fs::OpenOptions::new().create_new(true).write(true).open(&temporary).map_err(|_| "无法写入临时文件，请选择其他位置")?;
            response.copy_to(&mut file).map_err(|_| "成片保存中断，请重试")?;
            file.sync_all().map_err(|_| "无法保存成片")?;
            drop(file);
            std::fs::rename(&temporary,&path).map_err(|_| "无法保存成片，文件可能已被打开")?;
            Ok(())
        })();
        if result.is_err() { let _=std::fs::remove_file(&temporary); }
        result.map(|_|true)
    }).await.map_err(|_| "成片保存失败")?
}

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
        .invoke_handler(tauri::generate_handler![backend_connection, save_xmp, save_film])
        .build(tauri::generate_context!()).expect("AI RAW Studio 启动失败");
    app.run(|app, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app.try_state::<Backend>() {
                if let Ok(mut child) = state.child.lock() { let _ = child.kill(); let _ = child.wait(); }
            }
        }
    });
}
