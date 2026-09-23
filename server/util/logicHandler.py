
from collections import defaultdict
from datetime import datetime, timezone

def get_hour(timestamp):
    return timestamp.replace(
        minute=0,
        second=0,
        microsecond=0
    )


def computeMetrics(entries_for_hour):
    metric = {
        "totalGoodClients" : 0,
        "totalBaseClients": 0,
        "totalBadClients" : 0,
    }
    for entires in entries_for_hour:


def computeData(entries):
    hourly_entries = defaultdict(list)

    for entry in entries:
        hour = get_hour(entry["itemTime"])
        hourly_entries[hour].append(entry)

    for hour in sorted(hourly_entries):
        entries_for_hour = hourly_entries[hour]


        # Your price consensus algorithm goes here
        # canonical_price = ...

        for entry in entries_for_hour:
            client_id = entry["clientId"]
            price = entry["itemValue"]

            # Determine whether this client's price
            # agrees with the canonical price
            # correct = ...

            # updateWeight(correct)

        # Store hourly result here
        # save_hourly_result(hour, canonical_price)
