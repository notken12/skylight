// Where the sun is, from the time alone. Plain TypeScript with no React or DOM.
// Uses the standard low-precision solar formulas (accurate to well under a degree), which is
// plenty for deciding whether the sun has set and drawing a sunset band on a world map.

const RAD = Math.PI / 180;

// Sun elevation at official sunset: the disc's top on the horizon, including refraction.
export const SUNSET_ELEVATION = -0.833;

function wrapLongitude(longitude: number): number {
  return ((((longitude + 180) % 360) + 360) % 360) - 180;
}

// The point on Earth where the sun is directly overhead, as [longitude, latitude] in degrees.
export function subsolarPoint(time: Date): [number, number] {
  const n = time.getTime() / 86_400_000 + 2_440_587.5 - 2_451_545.0; // days since J2000
  const meanLongitude = (280.46 + 0.9856474 * n) % 360;
  const meanAnomaly = ((357.528 + 0.9856003 * n) % 360) * RAD;
  const eclipticLongitude = (meanLongitude + 1.915 * Math.sin(meanAnomaly) + 0.02 * Math.sin(2 * meanAnomaly)) * RAD;
  const obliquity = (23.439 - 0.0000004 * n) * RAD;
  const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLongitude));
  const rightAscension = Math.atan2(Math.cos(obliquity) * Math.sin(eclipticLongitude), Math.cos(eclipticLongitude));
  const siderealDegrees = ((18.697374558 + 24.06570982441908 * n) % 24) * 15;
  return [wrapLongitude(rightAscension / RAD - siderealDegrees), declination / RAD];
}

// Height of the sun above the horizon at a place, in degrees (negative below it).
export function sunElevation(latitude: number, longitude: number, time: Date): number {
  const [sunLongitude, declination] = subsolarPoint(time);
  const hourAngle = (longitude - sunLongitude) * RAD;
  const lat = latitude * RAD;
  const dec = declination * RAD;
  return Math.asin(Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(hourAngle)) / RAD;
}

// The line where the sun is setting right now, as line segments of [longitude, latitude].
// For each latitude it solves for the evening point where the sun sits at SUNSET_ELEVATION.
// Latitudes in polar day or night have no sunset and break the line; segments also split
// where the line crosses the antimeridian so maps don't draw a stroke across the world.
export function sunsetLine(time: Date, stepDegrees = 1): [number, number][][] {
  const [sunLongitude, declination] = subsolarPoint(time);
  const dec = declination * RAD;
  const segments: [number, number][][] = [];
  let current: [number, number][] = [];
  for (let latitude = -85; latitude <= 85; latitude += stepDegrees) {
    const lat = latitude * RAD;
    const cosHourAngle = (Math.sin(SUNSET_ELEVATION * RAD) - Math.sin(lat) * Math.sin(dec)) / (Math.cos(lat) * Math.cos(dec));
    if (Math.abs(cosHourAngle) > 1) {
      if (current.length > 1) segments.push(current);
      current = [];
      continue;
    }
    const longitude = wrapLongitude(sunLongitude + Math.acos(cosHourAngle) / RAD);
    const previous = current[current.length - 1];
    if (previous && Math.abs(longitude - previous[0]) > 180) {
      if (current.length > 1) segments.push(current);
      current = [];
    }
    current.push([longitude, latitude]);
  }
  if (current.length > 1) segments.push(current);
  return segments;
}
