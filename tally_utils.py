import httpx
from fastapi import HTTPException

TALLY_URL = "http://localhost:9000"

def _post_to_tally(xml_str: str) -> dict:
    import asyncio
    async def inner():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    TALLY_URL,
                    content=xml_str,
                    headers={"Content-Type": "application/xml"},
                )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail="Cannot connect to Tally at " + TALLY_URL + ". Is Tally running with HTTP server enabled on port 9000?",
            )
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Tally request timed out")

        tally_response = response.text
        is_error = (
            "LINEERROR" in tally_response
            or "ERROR" in tally_response.upper()
            and "CREATED" not in tally_response.upper()
        )
        return {
            "status": "error" if is_error else "success",
            "tally_response": tally_response,
            "xml_sent": xml_str,
        }
    return asyncio.run(inner())
