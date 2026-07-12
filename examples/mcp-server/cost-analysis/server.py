from fastmcp import FastMCP
from datetime import datetime, timedelta
import boto3
import json

mcp = FastMCP("AWS Cost Analysis")

ce_client = boto3.client("ce")


@mcp.tool(description="Get total AWS cost for a specified number of recent days (default 30 days)")
def get_total_cost(days: int = 30) -> str:
    """Get the total AWS cost for the specified period.

    Args:
        days: Number of days to look back (default 30)

    Returns:
        JSON string with total cost and currency
    """
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )

    total = 0.0
    for result in response["ResultsByTime"]:
        total += float(result["Total"]["UnblendedCost"]["Amount"])

    return json.dumps({
        "period": f"{start} ~ {end}",
        "total_cost": f"${total:.2f}",
        "currency": "USD",
    })


@mcp.tool(description="Get AWS cost breakdown by service for a specified number of recent days (default 30 days)")
def get_cost_by_service(days: int = 30, top_n: int = 10) -> str:
    """Get cost breakdown grouped by AWS service.

    Args:
        days: Number of days to look back (default 30)
        top_n: Number of top services to return (default 10)

    Returns:
        JSON string with per-service cost breakdown
    """
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    service_costs = {}
    for result in response["ResultsByTime"]:
        for group in result["Groups"]:
            service = group["Keys"][0]
            cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
            service_costs[service] = service_costs.get(service, 0.0) + cost

    sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)[:top_n]

    return json.dumps({
        "period": f"{start} ~ {end}",
        "top_services": [
            {"service": name, "cost": f"${cost:.2f}"}
            for name, cost in sorted_services
        ],
    })


@mcp.tool(description="Get daily AWS cost trend for a specified number of recent days (default 14 days)")
def get_daily_cost_trend(days: int = 14) -> str:
    """Get daily cost trend to identify spending patterns.

    Args:
        days: Number of days to look back (default 14)

    Returns:
        JSON string with daily cost data
    """
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
    )

    daily_costs = []
    for result in response["ResultsByTime"]:
        daily_costs.append({
            "date": result["TimePeriod"]["Start"],
            "cost": f"${float(result['Total']['UnblendedCost']['Amount']):.2f}",
        })

    return json.dumps({
        "period": f"{start} ~ {end}",
        "daily_costs": daily_costs,
    })


@mcp.tool(description="Get cost comparison between current and previous period")
def get_cost_comparison(days: int = 30) -> str:
    """Compare cost between current period and the same-length previous period.

    Args:
        days: Length of each period in days (default 30)

    Returns:
        JSON string with current vs previous period cost and change percentage
    """
    now = datetime.utcnow()
    current_end = now.strftime("%Y-%m-%d")
    current_start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    previous_end = current_start
    previous_start = (now - timedelta(days=days * 2)).strftime("%Y-%m-%d")

    # Current period
    current_response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": current_start, "End": current_end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    current_total = sum(
        float(r["Total"]["UnblendedCost"]["Amount"])
        for r in current_response["ResultsByTime"]
    )

    # Previous period
    previous_response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": previous_start, "End": previous_end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    previous_total = sum(
        float(r["Total"]["UnblendedCost"]["Amount"])
        for r in previous_response["ResultsByTime"]
    )

    change_pct = ((current_total - previous_total) / previous_total * 100) if previous_total > 0 else 0

    return json.dumps({
        "current_period": f"{current_start} ~ {current_end}",
        "current_cost": f"${current_total:.2f}",
        "previous_period": f"{previous_start} ~ {previous_end}",
        "previous_cost": f"${previous_total:.2f}",
        "change_percentage": f"{change_pct:+.1f}%",
        "trend": "increase" if change_pct > 0 else "decrease" if change_pct < 0 else "stable",
    })


@mcp.tool(description="Get cost for a specific AWS service over a specified number of recent days")
def get_service_cost_detail(service_name: str, days: int = 30) -> str:
    """Get detailed cost for a specific AWS service.

    Args:
        service_name: AWS service name (e.g., 'Amazon Elastic Compute Cloud - Compute', 'Amazon S3')
        days: Number of days to look back (default 30)

    Returns:
        JSON string with daily cost for the specified service
    """
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        Filter={
            "Dimensions": {
                "Key": "SERVICE",
                "Values": [service_name],
            }
        },
    )

    daily_costs = []
    total = 0.0
    for result in response["ResultsByTime"]:
        cost = float(result["Total"]["UnblendedCost"]["Amount"])
        total += cost
        daily_costs.append({
            "date": result["TimePeriod"]["Start"],
            "cost": f"${cost:.2f}",
        })

    return json.dumps({
        "service": service_name,
        "period": f"{start} ~ {end}",
        "total_cost": f"${total:.2f}",
        "daily_costs": daily_costs,
    })


if __name__ == "__main__":
    mcp.run()
