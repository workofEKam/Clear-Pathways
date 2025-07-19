function initMap(address) {
    // Geocode address to lat/lng (simple fallback; in real app, use Geocoding API)
    // For basic prototype, hardcoded center - replace with real coords if needed
    const map = new google.maps.Map(document.getElementById("map"), {
        center: { lat: 37.7749, lng: -122.4194 },  // Default: San Francisco
        zoom: 13,
    });
    new google.maps.Marker({
        position: { lat: 37.7749, lng: -122.4194 },
        map,
        title: address,
    });
}
