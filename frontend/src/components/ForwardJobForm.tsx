import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "motion/react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const schema = z.object({
  job_url: z
    .string()
    .min(1, "Paste a URL")
    .url("Must be a full URL (https://...)")
    .refine(
      (v) => v.startsWith("http://") || v.startsWith("https://"),
      "URL must start with http(s)://",
    ),
});

type FormValues = z.infer<typeof schema>;

interface Props {
  onSubmit: (jobUrl: string) => void;
  disabled?: boolean;
}

export default function ForwardJobForm({ onSubmit, disabled }: Props) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { job_url: "" },
  });

  return (
    <form
      onSubmit={handleSubmit((values) => onSubmit(values.job_url))}
      className="space-y-4"
    >
      <div className="flex gap-2">
        <div className="relative flex-1 group">
           <div className="absolute -inset-0.5 bg-primary/20 rounded-lg blur opacity-0 group-focus-within:opacity-100 transition duration-300"></div>
           <Input
            type="url"
            className="relative bg-background border-canvas focus:border-primary/50 font-mono text-xs h-11"
            placeholder="PASTE THE SUSPECT URL HERE..."
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            aria-invalid={Boolean(errors.job_url)}
            {...register("job_url")}
          />
        </div>
        <motion.div
          whileTap={{ scale: 0.95 }}
          className="h-11"
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
      {errors.job_url ? (
        <p className="text-[10px] font-mono text-destructive uppercase tracking-widest px-1" role="alert">
          ERROR: {errors.job_url.message}
        </p>
      ) : (
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest px-1 opacity-50">
          Awaiting input signal...
        </p>
      )}
    </form>
  );
}
