"use client";

/**
 * Radix-based overlay & navigation components in the shadcn/ui pattern:
 * Dialog, AlertDialog-style ConfirmDialog, DropdownMenu, ContextMenu,
 * Tooltip, Tabs, Select, Popover, Sheet (side dialog).
 */
import * as React from "react";
import {
  ContextMenu as ContextMenuPrimitive,
  Dialog as DialogPrimitive,
  DropdownMenu as DropdownPrimitive,
  Popover as PopoverPrimitive,
  Select as SelectPrimitive,
  Tabs as TabsPrimitive,
  Tooltip as TooltipPrimitive,
} from "radix-ui";
import { Check, ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

/* ---------------- Dialog ---------------- */

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  side,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: "right" }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 border border-border-strong bg-popover text-popover-foreground shadow-pop focus:outline-none",
          side === "right"
            ? "inset-y-0 right-0 flex h-full w-full max-w-2xl flex-col border-y-0 border-r-0 data-[state=open]:animate-in data-[state=open]:slide-in-from-right"
            : "left-1/2 top-1/2 grid w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl p-6 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close asChild>
          <Button variant="subtle" size="icon-sm" className="absolute right-3 top-3" aria-label="Close">
            <X />
          </Button>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("grid gap-1 pr-8", className)} {...props} />;
}
export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)} {...props} />;
}
export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn("text-base font-semibold", className)} {...props} />;
}
export function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn("text-[14px] text-muted-foreground", className)} {...props} />;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive,
  loading,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  children?: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent role="alertdialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>
        {children}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant={destructive ? "destructive" : "default"} loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ---------------- Menus ---------------- */

const menuContent =
  "z-50 min-w-40 overflow-hidden rounded-lg border border-border-strong bg-popover p-1.5 text-popover-foreground shadow-pop data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95";
const menuItem =
  "relative flex cursor-default select-none items-center gap-2 rounded-md px-2.5 py-2 text-[14px] outline-none transition-colors data-[highlighted]:bg-primary-soft data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[variant=destructive]:text-destructive [&_svg]:size-3.5 [&_svg]:text-muted-foreground data-[variant=destructive]:[&_svg]:text-destructive";

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;
export const DropdownMenuGroup = DropdownPrimitive.Group;

export function DropdownMenuContent({
  className,
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof DropdownPrimitive.Content>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content sideOffset={sideOffset} className={cn(menuContent, className)} {...props} />
    </DropdownPrimitive.Portal>
  );
}
export function DropdownMenuItem({
  className,
  variant,
  ...props
}: React.ComponentProps<typeof DropdownPrimitive.Item> & { variant?: "destructive" }) {
  return <DropdownPrimitive.Item data-variant={variant} className={cn(menuItem, className)} {...props} />;
}
export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof DropdownPrimitive.Label>) {
  return <DropdownPrimitive.Label className={cn("px-2 py-1.5 text-[13px] text-muted-foreground", className)} {...props} />;
}
export function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof DropdownPrimitive.Separator>) {
  return <DropdownPrimitive.Separator className={cn("-mx-1 my-1 h-px bg-border", className)} {...props} />;
}

export const ContextMenu = ContextMenuPrimitive.Root;
export const ContextMenuTrigger = ContextMenuPrimitive.Trigger;
export function ContextMenuContent({ className, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.Content>) {
  return (
    <ContextMenuPrimitive.Portal>
      <ContextMenuPrimitive.Content className={cn(menuContent, className)} {...props} />
    </ContextMenuPrimitive.Portal>
  );
}
export function ContextMenuItem({
  className,
  variant,
  ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.Item> & { variant?: "destructive" }) {
  return <ContextMenuPrimitive.Item data-variant={variant} className={cn(menuItem, className)} {...props} />;
}
export function ContextMenuSeparator({ className, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.Separator>) {
  return <ContextMenuPrimitive.Separator className={cn("-mx-1 my-1 h-px bg-border", className)} {...props} />;
}

/* ---------------- Tooltip ---------------- */

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({
  content,
  children,
  side = "top",
  shortcut,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  shortcut?: string;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className="z-50 flex max-w-xs items-center gap-2 rounded-md border border-border-strong bg-popover px-2.5 py-1.5 text-[13px] text-popover-foreground shadow-pop data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0"
        >
          {content}
          {shortcut ? <span className="font-mono text-[11px] text-muted-foreground">{shortcut}</span> : null}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/* ---------------- Popover ---------------- */

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export function PopoverContent({
  className,
  sideOffset = 6,
  align = "start",
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        sideOffset={sideOffset}
        align={align}
        className={cn(
          "z-50 w-72 rounded-lg border border-border-strong bg-popover p-3 text-popover-foreground shadow-pop outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0",
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}

/* ---------------- Tabs ---------------- */

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn("inline-flex items-center gap-0.5 border-b border-border", className)}
      {...props}
    />
  );
}
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "-mb-px inline-flex h-8 items-center gap-1.5 border-b-2 border-transparent px-2.5 text-[14px] text-muted-foreground transition-colors hover:text-foreground",
        "data-[state=active]:border-primary data-[state=active]:text-foreground [&_svg]:size-3.5",
        className,
      )}
      {...props}
    />
  );
}
export function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("outline-none", className)} {...props} />;
}

/* ---------------- Select ---------------- */

export function Select<T extends string>({
  value,
  onValueChange,
  options,
  placeholder,
  id,
  className,
  "aria-label": ariaLabel,
  disabled,
}: {
  value: T | undefined;
  onValueChange: (v: T) => void;
  options: readonly { value: T; label: string }[];
  placeholder?: string;
  id?: string;
  className?: string;
  "aria-label"?: string;
  disabled?: boolean;
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={(v) => onValueChange(v as T)} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn(
          "flex h-9 w-full items-center justify-between gap-2 rounded-sm border border-input bg-surface/70 px-3 text-[14px] transition-[border-color,box-shadow] hover:border-border-strong data-[placeholder]:text-subtle-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/20 disabled:opacity-50",
          className,
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className={cn(menuContent, "max-h-72 min-w-[var(--radix-select-trigger-width)]")}
        >
          <SelectPrimitive.Viewport>
            {options.map((o) => (
              <SelectPrimitive.Item key={o.value} value={o.value} className={cn(menuItem, "pr-7")}>
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-2">
                  <Check />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

/* ---------------- Segmented control ---------------- */

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: readonly { value: T; label: React.ReactNode; description?: string }[];
  "aria-label": string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={cn("inline-flex w-fit rounded-md border border-input bg-surface/70 p-0.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.description}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-[14px] transition-colors [&_svg]:size-3.5",
              active ? "bg-primary-soft text-foreground ring-1 ring-primary/30" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
