import uvicorn
from main_app import app
from main_configs import MAIN_APP_HOST, MAIN_APP_PORT

## Uvicorn runner (runtime only) for local development and testing
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=MAIN_APP_HOST,
        port=MAIN_APP_PORT,
        reload=True,
    )