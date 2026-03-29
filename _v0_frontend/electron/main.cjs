const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const os = require('os');

let mainWindow = null;
let pythonProcess = null;

function killPort(port) {
  try {
    const { execSync } = require('child_process');
    const pid = execSync(`lsof -ti:${port} 2>/dev/null`, { encoding: 'utf8' }).trim();
    if (pid) {
      execSync(`kill -9 ${pid} 2>/dev/null`, { encoding: 'utf8' });
      console.log(`Killed stale process on port ${port} (PID: ${pid})`);
    }
  } catch (e) {
    // No process on that port, or kill failed — safe to ignore
  }
}

function createPythonBackend() {
  const isDev = process.env.ELECTRON_IS_DEV === '1';
  // Point to the root backend/main.py
  const scriptPath = isDev 
    ? path.join(__dirname, '../../backend/main.py')
    : path.join(process.resourcesPath, 'backend/main.py');
    
  const venvPythonPath = isDev
    ? path.join(__dirname, '../../backend/venv/bin/python')
    : path.join(process.resourcesPath, 'backend/venv/bin/python');

  const fs = require('fs');
  const pythonExecutable = fs.existsSync(venvPythonPath) ? venvPythonPath : 'python3';

  // Kill any stale process on our port before starting
  killPort(6500);

  // Start the FastAPI backend
  pythonProcess = spawn(pythonExecutable, [scriptPath], {
    cwd: path.dirname(scriptPath),
    stdio: 'inherit'
  });

  pythonProcess.on('exit', (code) => {
    console.log(`Python backend exited with code ${code}`);
  });
}



function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs')
    }
  });

  const isDev = process.env.ELECTRON_IS_DEV === '1';
  if (isDev) {
    mainWindow.loadURL('http://localhost:3008');
    // mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  ipcMain.handle('dialog:openDirectory', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory']
    });
    if (canceled) {
      return null;
    } else {
      return filePaths[0];
    }
  });

  createPythonBackend();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  if (pythonProcess) {
    console.log('Killing python backend');
    pythonProcess.kill();
  }
});
