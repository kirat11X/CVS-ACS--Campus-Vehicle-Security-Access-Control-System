from backend.app.routes.vehicles import router as vehicles_router
from backend.app.routes.gates import router as gates_router
from backend.app.routes.observations import router as observations_router
from backend.app.routes.auth import router as auth_router
from backend.app.routes.owners import router as owners_router
from backend.app.routes.feed import router as feed_router
from backend.app.routes.resolutions import router as resolutions_router
from backend.app.routes.lanes import router as lanes_router
from backend.app.routes.movements import router as movements_router
from backend.app.routes.presence import router as presence_router

__all__ = [
    "vehicles_router",
    "gates_router",
    "observations_router",
    "auth_router",
    "owners_router",
    "feed_router",
    "resolutions_router",
    "lanes_router",
    "movements_router",
    "presence_router",
]
