const BASE = "https://xvvwesom7h.execute-api.us-east-1.amazonaws.com";

async function fetchAPI(url, options = {}) {
    try {
        const res = await fetch(url, {
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            ...options
        });

        console.log("STATUS:", res.status);

        const text = await res.text();
        console.log("RAW:", text);

        const json = JSON.parse(text);
        console.log("JSON:", json);

        return json;
    } catch (err) {
        console.error("ERROR:", err);
        return null;
    }
}

async function getHospitals() {
    const json = await fetchAPI(BASE + "/v1/hospitals");

    if (!json) return [];
    if (Array.isArray(json.data)) return json.data;

    return [];
}

async function getHospital(id) {
    const json = await fetchAPI(BASE + "/v1/hospitals/" + id);
    return json?.data;
}

async function getResources(id) {
    const json = await fetchAPI(BASE + "/v1/hospitals/" + id + "/resources");
    return json?.data || { resources: [] };
}

async function searchResource(type) {
    const json = await fetchAPI(BASE + "/v1/resources/" + type + "/hospitals");
    return json?.data || { hospitals: [] };
}

async function updateResource(id, type, qty) {
    return await fetchAPI(
        BASE + "/v1/hospitals/" + id + "/resources/" + type,
        {
            method: "PUT",
            body: JSON.stringify({ availableQuantity: Number(qty) })
        }
    );
}