from decimal import Decimal


async def account(client, name="Jane Doe"):
    response = await client.post("/api/v1/accounts", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def entry(client, account_id, amount="100.00", kind="credit", reference="DEP-001", **extra):
    return await client.post(
        f"/api/v1/accounts/{account_id}/transactions",
        json={"type": kind, "amount": amount, "reference_id": reference, **extra},
    )


async def balance(client, account_id):
    response = await client.get(f"/api/v1/accounts/{account_id}/balance")
    assert response.status_code == 200, response.text
    return Decimal(response.json()["balance"])


async def history(client, account_id, **params):
    response = await client.get(f"/api/v1/accounts/{account_id}/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def transfer_payload(source, destination, amount="30.00", reference="TRF-001", **extra):
    return {
        "source_account_id": source,
        "destination_account_id": destination,
        "amount": amount,
        "reference_id": reference,
        **extra,
    }
