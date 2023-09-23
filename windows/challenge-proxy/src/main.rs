use std::ffi::OsString;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use eyre::WrapErr;
use log::{debug, error, info};
use once_cell::sync::Lazy;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;
use windows_service::{
    define_windows_service,
    service::{
        ServiceControl, ServiceControlAccept, ServiceExitCode, ServiceState, ServiceStatus,
        ServiceType,
    },
    service_control_handler::{self, ServiceControlHandlerResult, ServiceStatusHandle},
    service_dispatcher,
};

const CHALLENGE_DIR: &'static str = "Y:\\";

fn find_challenge_binary() -> eyre::Result<PathBuf> {
    let dir = PathBuf::from(CHALLENGE_DIR);
    for entry in dir
        .read_dir()
        .wrap_err_with(|| format!("Failed to read directory {:?}", CHALLENGE_DIR))?
    {
        let entry =
            entry.wrap_err_with(|| format!("Failed to read directory {:?}", CHALLENGE_DIR))?;
        match entry.path().extension() {
            Some(ext) if ext == "exe" => {
                return Ok(entry.path());
            }
            _ => {}
        }
    }
    Err(eyre::eyre!(
        "Failed to find a .exe file in {:?}",
        CHALLENGE_DIR
    ))
}

async fn client_handler(mut socket: TcpStream) -> eyre::Result<()> {
    const BUFSIZE: usize = 4096;
    let mut stdin_buf = vec![0; BUFSIZE];
    let mut stdout_buf = vec![0; BUFSIZE];
    let mut stderr_buf = vec![0; BUFSIZE];

    info!("Handling connection");
    let challenge_binary = find_challenge_binary()?;
    let mut child = tokio::process::Command::new(&challenge_binary)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .wrap_err_with(|| format!("Failed to spawn child process {:?}", &challenge_binary))?;
    let mut stdin = child.stdin.take().unwrap();
    let mut stdout = child.stdout.take().unwrap();
    let mut stderr = child.stderr.take().unwrap();

    loop {
        tokio::select! {
            n = socket.read(&mut stdin_buf) => {
                let n = n.wrap_err("Failed to read from socket")?;
                if n == 0 {
                    info!("client disconnect");
                    return Ok(());
                }
                debug!("stdin: read {} bytes", n);
                stdin.write_all(&stdin_buf[0..n]).await.wrap_err("Failed to write to child stdin")?;
            }
            n = stdout.read(&mut stdout_buf) => {
                let n = n.wrap_err("Failed to read from child stdout")?;
                if n == 0 {
                    info!("stdout: process exit");
                    return Ok(());
                }
                debug!("stdout: read {} bytes", n);
                socket.write_all(&stdout_buf[0..n]).await.wrap_err("Failed to write to socket")?;
            }
            n = stderr.read(&mut stderr_buf) => {
                let n = n.wrap_err("Failed to read from child stderr")?;
                if n == 0 {
                    info!("stderr: process exit");
                    return Ok(());
                }
                debug!("stderr: read {} bytes", n);
                socket.write_all(&stderr_buf[0..n]).await.wrap_err("Failed to write to socket")?;
            }
            status = child.wait() => {
                let status = status.wrap_err("Failed to wait for process")?;
                info!("child exited with status {}", status);
                return Ok(());
            }
        }
    }
}

async fn server_entry(mut stop_channel: oneshot::Receiver<()>) -> eyre::Result<()> {
    let addr = "0.0.0.0:4001";
    let listener = TcpListener::bind(addr).await?;
    info!("listening on {addr}");

    loop {
        tokio::select! {
            _ = &mut stop_channel => {
                break Ok(())
            }
            r = listener.accept() => {
                let (socket, _) = r?;
                tokio::spawn(async move {
                    match client_handler(socket).await {
                        Ok(_) => {}
                        Err(e) => error!("Error handling connection: {:?}", e),
                    }
                });
            }
        }
    }
}

const SERVICE_NAME: &'static str = "ChallengeProxy";
static SERVICE_HANDLE: Lazy<Arc<Mutex<Option<ServiceStatusHandle>>>> =
    Lazy::new(|| Arc::new(Mutex::new(None)));
static STOP_CHANNEL: Lazy<Arc<Mutex<Option<oneshot::Sender<()>>>>> =
    Lazy::new(|| Arc::new(Mutex::new(None)));

fn windows_service_main(_arguments: Vec<OsString>) {
    let next_status = ServiceStatus {
        // Should match the one from system service registry
        service_type: ServiceType::OWN_PROCESS,
        // The new state
        current_state: ServiceState::Running,
        // Accept stop events when running
        controls_accepted: ServiceControlAccept::STOP,
        // Used to report an error when starting or stopping only, otherwise must be zero
        exit_code: ServiceExitCode::Win32(0),
        // Only used for pending states, otherwise must be zero
        checkpoint: 0,
        // Only used for pending states, otherwise must be zero
        wait_hint: Duration::default(),
        // process ID retrieved when querying service status
        process_id: Some(std::process::id()),
    };
    let (tx, rx) = oneshot::channel();
    *STOP_CHANNEL.lock().unwrap() = Some(tx);
    let event_handler = {
        let mut next_status = next_status.clone();
        move |control_event: ServiceControl| -> ServiceControlHandlerResult {
            match control_event {
                ServiceControl::Stop => {
                    if let Some(tx) = STOP_CHANNEL.lock().unwrap().take() {
                        let _ = tx.send(());
                    }
                    next_status.current_state = ServiceState::StopPending;
                    let _ = SERVICE_HANDLE
                        .lock()
                        .unwrap()
                        .unwrap()
                        .set_service_status(next_status.clone());
                    ServiceControlHandlerResult::NoError
                }
                ServiceControl::Interrogate => ServiceControlHandlerResult::NoError,
                _ => ServiceControlHandlerResult::NotImplemented,
            }
        }
    };
    *SERVICE_HANDLE.lock().unwrap() =
        Option::Some(service_control_handler::register(SERVICE_NAME, event_handler).unwrap());

    SERVICE_HANDLE
        .lock()
        .unwrap()
        .unwrap()
        .set_service_status(next_status.clone())
        .unwrap();
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async move {
            let mut next_status = next_status.clone();
            let r = server_entry(rx).await;
            next_status.current_state = ServiceState::Stopped;
            match r {
                Ok(()) => {
                    info!("Server exiting gracefully");
                }
                Err(err) => {
                    error!("Server fatal error: {:?}", err);
                    next_status.exit_code = ServiceExitCode::Win32(1);
                }
            };
            let _ = SERVICE_HANDLE
                .lock()
                .unwrap()
                .unwrap()
                .set_service_status(next_status.clone());
        });
}

define_windows_service!(ffi_service_main, windows_service_main);

fn main() -> eyre::Result<()> {
    #[cfg(target_os = "windows")]
    {
        winlog::try_register(SERVICE_NAME).unwrap();
        winlog::init(SERVICE_NAME).expect("failed to initialize windows log");
        // init sets level to debug, so set it back afterwards
        log::set_max_level(log::LevelFilter::Info);
        service_dispatcher::start(SERVICE_NAME, ffi_service_main).unwrap();
        Ok(())
    }
    #[cfg(not(target_os = "windows"))]
    {
        env_logger::init();
        let (tx, rx) = oneshot::channel();
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async move { server_entry(rx).await })
    }
}
