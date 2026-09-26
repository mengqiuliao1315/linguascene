import { BASE_PATH } from "./api";

export const OPENING_AUDIO: Record<string, { text: string; file: string }> = {
  "ordering-coffee": {
    text: "Hi there! What can I get for you today?",
    file: "/audio/openings/ordering-coffee.mp3",
  },
  "airport-check-in": {
    text: "Good morning! Where are you flying to today?",
    file: "/audio/openings/airport-check-in.mp3",
  },
  "hotel-check-in": {
    text: "Good evening! Welcome to the Riverside Hotel. Do you have a reservation?",
    file: "/audio/openings/hotel-check-in.mp3",
  },
  "restaurant": {
    text: "Good evening! Here's the menu. Can I get you something to drink first?",
    file: "/audio/openings/restaurant.mp3",
  },
  "job-interview": {
    text: "Thanks for coming in today. Could you start by telling me a bit about yourself?",
    file: "/audio/openings/job-interview.mp3",
  },
  "grocery-shopping": {
    text: "Hi! Let me know if you need help finding anything.",
    file: "/audio/openings/grocery-shopping.mp3",
  },
  "taxi-ride": {
    text: "Evening! Where are you headed?",
    file: "/audio/openings/taxi-ride.mp3",
  },
  "doctor-visit": {
    text: "Hello, please have a seat. What brings you in today?",
    file: "/audio/openings/doctor-visit.mp3",
  },
  "bank-account": {
    text: "Good morning. How can I help you today?",
    file: "/audio/openings/bank-account.mp3",
  },
  "apartment-renting": {
    text: "Hi! Thanks for coming to see the apartment. What would you like to know first?",
    file: "/audio/openings/apartment-renting.mp3",
  },
  "team-meeting": {
    text: "Let's get started. Could you give us a quick update on your work?",
    file: "/audio/openings/team-meeting.mp3",
  },
  "party-small-talk": {
    text: "Hey, good to see you! How do you know the host?",
    file: "/audio/openings/party-small-talk.mp3",
  },
  "free-talk": {
    text: "Hey! What would you like to talk about today?",
    file: "/audio/openings/free-talk.mp3",
  },
};

export function staticOpeningUrl(
  slug: string | null | undefined,
  text: string
): string | null {
  if (!slug) return null;
  const entry = OPENING_AUDIO[slug];
  if (!entry || entry.text !== text) return null;
  return `${BASE_PATH}${entry.file}`;
}
