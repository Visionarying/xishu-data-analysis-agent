@echo off
rem 析数 · 数据分析 Agent 一键启动
cd /d "D:\ai\opencode\工作区\data-analysis-agent"
setlocal
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
start "数据分析Agent 服务" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8000/"
echo.
echo  服务已启动：http://127.0.0.1:8000/
echo  若浏览器提示连接被拒绝，请等几秒后刷新。
echo  关闭弹出的黑色服务窗口即可停止应用。
