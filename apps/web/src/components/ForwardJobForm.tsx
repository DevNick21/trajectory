import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "motion/react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

const schema = z.object({
  input: z
    .string()
    .min(1, "Paste a job URL or job description")
    .refine((v) => {
      const trimmed = v.trim();
      if (/^https?:\/\//i.test(trimmed)) {
        try {
          new URL(trimmed);
          return true;
        } catch {
          return false;
        }
      }
      return trimmed.length >= 40;
    }, "Paste a valid http(s) URL or at least 40 characters of job text"),
});

type FormValues = z.infer<typeof schema>;

interface Props {
  onSubmit: (input: string) => void;
  disabled?: boolean;
}

export default function ForwardJobForm({ onSubmit, disabled }: Props) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { input: "" },
  });

  return (
    <form
      onSubmit={handleSubmit((values) => onSubmit(values.input.trim()))}
      className="space-y-4"
    >
      <div className="flex flex-col gap-3">
        <div className="relative flex-1 group">
           <div className="absolute -inset-0.5 bg-primary/20 rounded-lg blur opacity-0 group-focus-within:opacity-100 transition duration-300"></div>
           <textarea
            className="relative flex min-h-28 w-full rounded-md border border-canvas bg-background px-3 py-3 font-mono text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
            placeholder="PASTE THE JOB URL OR JOB DESCRIPTION HERE..."
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            aria-invalid={Boolean(errors.input)}
            {...register("input")}
          />
        </div>
        <motion.div
          whileTap={{ scale: 0.95 }}
          className="h-11 self-end"
        >
          <Button type="submit" disabled={disabled} className="h-full px-8 font-black uppercase tracking-[0.2em] text-xs">
            {disabled ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                SCRUTINIZING
              </>
            ) : (
              "JUDGE IT"
            )}
          </Button>
        </motion.div>
      </div>
      {errors.input ? (
        <p className="text-[10px] font-mono text-destructive uppercase tracking-widest px-1" role="alert">
          ERROR: {errors.input.message}
        </p>
      ) : (
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest px-1 opacity-50">
          URL runs the full stream. Pasted JD text runs a local first-pass analysis.
        </p>
      )}
    </form>
  );
}
