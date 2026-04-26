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
      className="space-y-2"
    >
      <div className="flex gap-2">
        <Input
          type="url"
          placeholder="https://example.com/jobs/senior-engineer"
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          aria-invalid={Boolean(errors.job_url)}
          {...register("job_url")}
        />
        <motion.div
          whileTap={{ scale: 0.97 }}
          transition={{ type: "spring", stiffness: 400, damping: 25 }}
        >
          <Button type="submit" disabled={disabled}>
            {disabled ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Checking…
              </>
            ) : (
              "Check"
            )}
          </Button>
        </motion.div>
      </div>
      {errors.job_url && (
        <p className="text-xs text-destructive" role="alert">
          {errors.job_url.message}
        </p>
      )}
    </form>
  );
}
