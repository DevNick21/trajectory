import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Wave 6 placeholder. Wave 9 builds the real wizard:
// tap-options + typed forms + free-text only for voice-capturing
// stages (motivations, deal-breakers, writing samples).

export default function Onboarding() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Onboarding</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        <p>
          The web onboarding wizard arrives in Wave 9 (MIGRATION_PLAN.md §8).
        </p>
        <p>
          Until then, complete onboarding on the Telegram bot — once your
          profile exists, both surfaces share it.
        </p>
      </CardContent>
    </Card>
  );
}
