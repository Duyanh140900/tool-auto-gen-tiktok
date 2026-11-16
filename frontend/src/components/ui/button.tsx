import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-all disabled:pointer-events-none disabled:opacity-50 outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background [&_svg]:pointer-events-none [&_svg]:size-4 shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-sm hover:brightness-110",
        secondary: "bg-accent text-accent-foreground shadow-sm hover:brightness-110",
        outline: "border border-border bg-transparent hover:bg-white/5",
        ghost: "bg-transparent hover:bg-white/5",
        destructive: "bg-destructive/20 text-red-100 border border-destructive/40 hover:bg-destructive/30",
      },
      size: {
        default: "h-11 px-4 py-2",
        sm: "h-9 rounded-lg px-3",
        lg: "h-12 rounded-xl px-5",
        icon: "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";

  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
