from flask import Flask, render_template, request

app = Flask(__name__)

def calculate(data):
    equipment = float(data.get("equipment", 0))
    model = data.get("model", "")
    pipe = float(data.get("pipe", 0))
    difficulty = float(data.get("difficulty", 1))
    electrical = float(data.get("electrical", 0))
    additional = float(data.get("additional", 0))
    slim_duct = float(data.get("slim_duct") or 0)
    thermostat = float(data.get("thermostat") or 0)
    sensor = float(data.get("sensor") or 0)
    neutralizer = float(data.get("neutralizer") or 0)
    pad = float(data.get("pad") or 0)
    heat_loss = float(data.get("heat_loss") or 0)
    customer = data.get("customer", "")
    address = data.get("address", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    date = data.get("date", "")

    materials = (equipment * 1.12) + 1000
    freight = 100
    permit = 200
    pipe_cost = pipe * 6
    labour = 1800 * difficulty
    SLIM_DUCT_RATE = 8
    slim_duct_cost = slim_duct * SLIM_DUCT_RATE

    subtotal = (
            equipment + materials + freight + permit +
            pipe_cost + slim_duct_cost + labour + electrical + additional +
            thermostat + sensor + neutralizer + pad + heat_loss
    )

    TAX_RATE = 0.05
    COMMISSION_RATE = 0.07

    commission = subtotal * COMMISSION_RATE
    subtotal_with_commission = subtotal + commission

    tax = subtotal_with_commission * TAX_RATE
    total = subtotal_with_commission + tax

    return {
        "customer": customer,
        "address": address,
        "phone": phone,
        "email": email,
        "date": date,
        "model": model,
        "materials": materials,
        "freight": freight,
        "permit": permit,
        "pipe_cost": pipe_cost,
        "slim_duct_cost": slim_duct_cost,
        "labour": labour,
        "thermostat": thermostat,
        "sensor": sensor,
        "neutralizer": neutralizer,
        "pad": pad,
        "heat_loss": heat_loss,
        "subtotal": subtotal,
        "commission": commission,
        "subtotal_with_commission": subtotal_with_commission,
        "tax": tax,
        "total": total
    }

@app.route("/", methods=["GET", "POST"])
def furnace():
    result = None
    if request.method == "POST":
        result = calculate(request.form)
    return render_template("furnace.html", result=result)

@app.route("/quote", methods=["POST"])
def quote():
    result = calculate(request.form)
    return render_template("quote.html", result=result)


if __name__ == "__main__":
    app.run(debug=True)
