import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Buttons are fully rounded pills, per the reference design.
 *
 * `mint` is deliberately scarce -- one per screen, on the thing the user came
 * to do (Save, Get started, Try the demo). Everything else is `ink` or
 * `outline`, so the green never has to compete with itself for attention.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-500 focus-visible:ring-offset-2 focus-visible:ring-offset-cream-100 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-mint-500 text-forest-950 hover:bg-mint-400",
        // For dark green surfaces, where mint-on-green is the wrong contrast.
        ink: "bg-ink text-cream-50 hover:bg-forest-800",
        secondary: "bg-cream-200 text-ink hover:bg-cream-300",
        outline: "border border-cream-300 bg-transparent text-ink hover:bg-cream-200",
        ghost: "text-ink-muted hover:bg-cream-200 hover:text-ink",
        destructive: "bg-rose-600 text-white hover:bg-rose-700",
      },
      size: {
        default: "h-10 px-5 py-2",
        sm: "h-8 px-3.5 text-xs",
        lg: "h-12 px-8 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as the child element instead of a <button> -- used to make a
   *  <Link> look like a button without nesting interactive elements. */
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
