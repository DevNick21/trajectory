import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

// Fix standard marker icon issue in React-Leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png",
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png",
});

interface JobMapProps {
  jobLocation?: string;
  userLocation?: string;
}

// Dummy geocoding function for demonstration
const geocode = async (location: string): Promise<[number, number] | null> => {
  if (!location) return null;
  const loc = location.toLowerCase();
  if (loc.includes("london")) return [51.5074, -0.1278];
  if (loc.includes("manchester")) return [53.4808, -2.2426];
  if (loc.includes("edinburgh")) return [55.9533, -3.1883];
  if (loc.includes("remote")) return null;

  // Random fallback for demonstration
  return [51.5 + Math.random() * 2, -0.1 + Math.random() * 2];
};

function CalculateDistance({ pos1, pos2, setDistance }: { pos1: [number, number], pos2: [number, number], setDistance: (d: number) => void }) {
  const map = useMap();
  useEffect(() => {
    const p1 = L.latLng(pos1[0], pos1[1]);
    const p2 = L.latLng(pos2[0], pos2[1]);
    const dist = p1.distanceTo(p2) / 1000; // in km
    setDistance(Math.round(dist));

    // Fit bounds
    const bounds = L.latLngBounds([p1, p2]);
    map.fitBounds(bounds, { padding: [50, 50] });
  }, [pos1, pos2, map, setDistance]);

  return null;
}

export default function JobMap({ jobLocation, userLocation }: JobMapProps) {
  const [jobPos, setJobPos] = useState<[number, number] | null>(null);
  const [userPos, setUserPos] = useState<[number, number] | null>(null);
  const [distance, setDistance] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadPositions() {
      setLoading(true);
      const jp = await geocode(jobLocation || "");
      const up = await geocode(userLocation || "London"); // Defaulting user to London if unknown
      setJobPos(jp);
      setUserPos(up);
      setLoading(false);
    }
    loadPositions();
  }, [jobLocation, userLocation]);

  if (loading) return <div className="h-[280px] flex items-center justify-center bg-[#0b101e] border-2 border-primary/20 rounded-xl animate-pulse text-muted-foreground text-sm">Mapping coordinates...</div>;
  if (!jobPos || !userPos) return <div className="h-[280px] flex items-center justify-center bg-[#0b101e] border-2 border-primary/20 rounded-xl text-sm text-muted-foreground">Location not mappable (Remote role)</div>;

  return (
    <Card className="overflow-hidden border-2 border-primary/20 bg-[#0b101e] shadow-lg z-0">
      <CardHeader className="bg-[#0f172a] border-b border-primary/10 py-3 relative z-10">
        <CardTitle className="text-sm font-bold flex justify-between items-center text-white">
          <span className="flex items-center gap-2">
            <span className="text-primary animate-pulse">●</span> Location Analysis
          </span>
          {distance !== null && (
            <span className="text-[10px] uppercase font-mono px-2 py-1 bg-primary/10 border border-primary/20 text-primary rounded-full">
              {distance} km away
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 h-[220px] relative z-0">
        {/* Note the URL change to dark_all for CartoDB Dark Matter */}
        <MapContainer center={userPos} zoom={13} scrollWheelZoom={false} className="h-full w-full relative z-0" style={{ filter: "invert(90%) hue-rotate(180deg) brightness(95%) contrast(85%)" }}>
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          />
          <Marker position={userPos}>
            <Popup>You are here ({userLocation || "London"})</Popup>
          </Marker>
          <Marker position={jobPos}>
            <Popup>Job Location ({jobLocation})</Popup>
          </Marker>
          <CalculateDistance pos1={userPos} pos2={jobPos} setDistance={setDistance} />
        </MapContainer>
      </CardContent>
    </Card>
  );
}
