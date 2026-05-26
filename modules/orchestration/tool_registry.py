from typing import Callable, Dict, Any

class ToolRegistry:
    _tools: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(func: Callable):
            cls._tools[name] = func
            return func
        return decorator

    @classmethod
    async def execute(cls, name: str, **kwargs) -> Any:
        if name not in cls._tools:
            raise ValueError(f"Tool {name} not registered")
        return await cls._tools[name](**kwargs)

# Example registration
@ToolRegistry.register("search_properties")
async def search_properties_tool(location: str, budget_max: int, bhk: int):
    from modules.realestate.repo import search_properties
    return await search_properties(location, budget_max, bhk)