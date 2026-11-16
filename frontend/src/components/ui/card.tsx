import * as React from "react";



import { cn } from "@/lib/utils";



function Card({ className, ...props }: React.ComponentProps<"div">) {

  return (

    <div

      data-slot="card"

      className={cn(

        "rounded-3xl border border-border bg-card/80 text-card-foreground shadow-[0_20px_70px_rgba(2,6,23,0.22)] backdrop-blur-xl",
        className,

      )}

      {...props}

    />

  );

}



function CardHeader({ className, ...props }: React.ComponentProps<"div">) {

  return <div data-slot="card-header" className={cn("flex flex-col gap-2 p-5 sm:p-6", className)} {...props} />;
}



function CardTitle({ className, ...props }: React.ComponentProps<"div">) {

  return <div data-slot="card-title" className={cn("text-lg font-semibold tracking-tight", className)} {...props} />;
}



function CardDescription({ className, ...props }: React.ComponentProps<"div">) {

  return <div data-slot="card-description" className={cn("text-sm leading-6 text-muted-foreground", className)} {...props} />;

}



function CardContent({ className, ...props }: React.ComponentProps<"div">) {

  return <div data-slot="card-content" className={cn("px-5 pb-5 sm:px-6 sm:pb-6", className)} {...props} />;
}



function CardFooter({ className, ...props }: React.ComponentProps<"div">) {

  return <div data-slot="card-footer" className={cn("flex items-center gap-3 px-6 pb-6", className)} {...props} />;

}



export { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle };

