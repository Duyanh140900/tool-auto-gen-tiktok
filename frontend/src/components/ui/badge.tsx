import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold tracking-wide transition-colors",
  {
    variants: {
      variant: {
        default: "border-primary/30 bg-primary/15 text-primary-foreground",
        secondary: "border-border bg-muted text-muted-foreground",
        outline: "border-border/80 bg-transparent text-foreground/80",
        success: "border-emerald-500/25 bg-emerald-500/15 text-emerald-200",
        warning: "border-amber-500/25 bg-amber-500/15 text-amber-100",
        destructive: "border-destructive/30 bg-destructive/15 text-red-100",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({ className, variant, ...props }: React.ComponentProps<"div"> & VariantProps<typeof badgeVariants>) {
  return <div data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
