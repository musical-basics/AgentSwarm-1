const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const os = require('os');

let mainWindow = null;
let pythonProcess = null;

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
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  const isDev = process.env.ELECTRON_IS_DEV === '1';
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
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
