# 🚀 Startup Commands

Single commands to run FastAPI and Celery for both development and production environments.

## 📋 Prerequisites

Make sure you have the following installed:
- Python 3.8+
- Virtual environment activated
- All dependencies installed (`pip install -r requirements.txt`)
- PostgreSQL running
- Redis running (for Celery)

## 🛠️ Available Commands

### Option 1: Python Script (Recommended)
```bash
# Development mode
python start_app.py dev

# Production mode  
python start_app.py prod
```

### Option 2: Shell Script
```bash
# Development mode
./start.sh dev

# Production mode
./start.sh prod
```

### Option 3: Manual Commands

#### Development Mode
```bash
# Terminal 1 - Start Celery
cd alhaq-backend
celery -A core.celery_app worker --loglevel=info --concurrency=2 --queues=default,emails,notifications

# Terminal 2 - Start FastAPI
cd alhaq-backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### Production Mode
```bash
# Terminal 1 - Start Celery
cd alhaq-backend
celery -A core.celery_app worker --loglevel=info --concurrency=4 --queues=default,emails,notifications

# Terminal 2 - Start FastAPI
cd alhaq-backend
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile -
```

## 🔧 What Each Mode Does

### Development Mode (`dev`)
- **FastAPI**: Uses `uvicorn` with auto-reload for development
- **Celery**: 2 worker processes for background tasks
- **Features**: Hot reload, detailed logging, faster startup

### Production Mode (`prod`)
- **FastAPI**: Uses `gunicorn` with 4 uvicorn workers for production
- **Celery**: 4 worker processes for better performance
- **Features**: Optimized for production, better error handling

## 🌐 Access Points

Once started, you can access:
- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Celery Monitoring**: Check logs for worker status

## 🛑 Stopping Services

- **Python/Shell Scripts**: Press `Ctrl+C` to stop all services
- **Manual**: Press `Ctrl+C` in each terminal

## 🔍 Troubleshooting

### Common Issues

1. **Port 8000 already in use**
   ```bash
   # Find and kill process using port 8000
   lsof -ti:8000 | xargs kill -9
   ```

2. **Celery connection error**
   ```bash
   # Make sure Redis is running
   redis-server
   ```

3. **Database connection error**
   ```bash
   # Make sure PostgreSQL is running
   sudo systemctl start postgresql
   ```

4. **Permission denied on scripts**
   ```bash
   chmod +x start_app.py start.sh
   ```

### Logs

- **FastAPI logs**: Displayed in terminal
- **Celery logs**: Displayed in terminal
- **Error logs**: Check terminal output for detailed error messages

## 📝 Environment Variables

Make sure these environment variables are set:
```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/alhaq"
export REDIS_URL="redis://localhost:6379"
export SECRET_KEY="your-secret-key"
export PAYSTACK_SECRET_KEY="your-paystack-key"
```

## 🚀 Quick Start

1. **Activate virtual environment**
   ```bash
   source .venv/bin/activate  # Linux/Mac
   # or
   .venv\Scripts\activate     # Windows
   ```

2. **Start services**
   ```bash
   python start_app.py dev
   ```

3. **Open browser**
   - Go to http://localhost:8000/docs
   - Test the API endpoints

4. **Stop services**
   - Press `Ctrl+C` in the terminal

## 📊 Monitoring

- **Health Check**: GET http://localhost:8000/health
- **API Status**: Check terminal output for request logs
- **Celery Status**: Check terminal output for task logs
