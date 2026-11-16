import * as React from "react";
import * as ToastPrimitives from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const ToastProvider = ToastPrimitives.Provider;

function ToastViewport({ className, ...props }: React.ComponentProps<typeof ToastPrimitives.Viewport>) {
  return (
    <ToastPrimitives.Viewport
      data-slot="toast-viewport"
      className={cn(
        "fixed top-0 z-[100] flex max-h-screen w-full flex-col-reverse p-4 sm:bottom-0 sm:right-0 sm:top-auto sm:flex-col md:max-w-[420px]",
        className,
      )}
      {...props}
    />
  );
}

const toastVariants = cva(
  "group pointer-events-auto relative flex w-full items-start justify-between gap-4 overflow-hidden rounded-2xl border p-4 pr-6 shadow-2xl backdrop-blur transition-all data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[swipe=move]:transition-none",
  {
    variants: {
      variant: {
        default: "border-border/80 bg-card/95 text-card-foreground",
        success: "border-emerald-500/30 bg-emerald-950/80 text-emerald-50",
        destructive: "border-destructive/30 bg-red-950/85 text-red-50",
        warning: "border-amber-500/30 bg-amber-950/85 text-amber-50",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Toast({ className, variant, ...props }: React.ComponentProps<typeof ToastPrimitives.Root> & VariantProps<typeof toastVariants>) {
  return <ToastPrimitives.Root data-slot="toast" className={cn(toastVariants({ variant }), className)} {...props} />;
}

function ToastAction({ className, ...props }: React.ComponentProps<typeof ToastPrimitives.Action>) {
  return (
    <ToastPrimitives.Action
      data-slot="toast-action"
      className={cn(
        "inline-flex h-9 shrink-0 items-center justify-center rounded-xl border border-border/70 px-3 text-sm font-medium transition-colors hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

function ToastClose({ className, ...props }: React.ComponentProps<typeof ToastPrimitives.Close>) {
  return (
    <ToastPrimitives.Close
      data-slot="toast-close"
      className={cn(
        "absolute right-2 top-2 rounded-md p-1 text-current/70 opacity-0 transition-opacity hover:text-current focus:opacity-100 focus:outline-none focus:ring-2 group-hover:opacity-100",
        className,
      )}
      toast-close=""
      {...props}
    >
      <X className="size-4" />
    </ToastPrimitives.Close>
  );
}

function ToastTitle({ className, ...props }: React.ComponentProps<typeof ToastPrimitives.Title>) {
  return <ToastPrimitives.Title data-slot="toast-title" className={cn("text-sm font-semibold", className)} {...props} />;
}

function ToastDescription({ className, ...props }: React.ComponentProps<typeof ToastPrimitives.Description>) {
  return <ToastPrimitives.Description data-slot="toast-description" className={cn("text-sm opacity-90", className)} {...props} />;
}

type ToastProps = React.ComponentProps<typeof Toast>;
type ToastActionElement = React.ReactElement<typeof ToastAction>;

export {
  Toast,
  ToastAction,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
  type ToastActionElement,
  type ToastProps,
};
