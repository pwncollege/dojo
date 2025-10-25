"use client"

import React, { useCallback, useState, forwardRef, useEffect } from "react"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { ChevronDown, CheckIcon } from "lucide-react"
import { CircleFlag } from "react-circle-flags"
import { countries } from "country-data-list"

export type Country = {
  alpha2: string
  alpha3: string
  countryCallingCodes: string[]
  currencies: string[]
  emoji?: string
  ioc: string
  languages: string[]
  name: string
  status: string
}

type CountrySelectorProps = {
  value?: string
  onValueChange?: (value: string) => void
  disabled?: boolean
  placeholder?: string
  className?: string
}

const CountrySelectorComponent = (
  {
    value,
    onValueChange,
    disabled = false,
    placeholder = "Select a country",
    className,
    ...props
  }: CountrySelectorProps,
  ref: React.ForwardedRef<HTMLButtonElement>
) => {
  const [open, setOpen] = useState(false)
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(null)

  const options = countries.all.filter(
    (country: Country) =>
      country.emoji && country.status !== "deleted" && country.ioc !== "PRK"
  )

  useEffect(() => {
    if (!value) {
      if (selectedCountry) setSelectedCountry(null)
      return
    }

    const country = options.find((c) => c.alpha2 === value)
    if (country && country.alpha2 !== selectedCountry?.alpha2) {
      setSelectedCountry(country)
    }
  }, [value, options])

  const handleSelect = useCallback(
    (country: Country) => {
      setSelectedCountry(country)
      onValueChange?.(country.alpha2)
      setOpen(false)
    },
    [onValueChange]
  )

  const triggerClasses = cn(
    "flex h-11 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 cursor-pointer hover:brightness-105 transition-all",
    className
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        ref={ref}
        className={triggerClasses}
        disabled={disabled}
        {...props}
      >
        {selectedCountry ? (
          <div className="flex items-center flex-grow gap-2 overflow-hidden">
            <div className="inline-flex items-center justify-center w-5 h-5 shrink-0 overflow-hidden rounded-full">
              <CircleFlag
                countryCode={selectedCountry.alpha2.toLowerCase()}
                height={20}
              />
            </div>
            <span className="overflow-hidden text-ellipsis whitespace-nowrap">
              {selectedCountry.name}
            </span>
          </div>
        ) : (
          <span className="text-muted-foreground">
            {placeholder}
          </span>
        )}

        <ChevronDown size={16} className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="start"
        className="w-[var(--radix-popover-trigger-width)] p-0"
        sideOffset={4}
      >
        <Command className="max-h-[300px]">
          <CommandList>
            <div className="sticky top-0 z-10 bg-popover">
              <CommandInput placeholder="Search country..." />
            </div>
            <CommandEmpty>No country found.</CommandEmpty>
            <CommandGroup>
              {options
                .filter((x) => x.name)
                .map((option, key: number) => (
                  <CommandItem
                    className="flex items-center w-full gap-2"
                    key={key}
                    onSelect={() => handleSelect(option)}
                  >
                    <div className="flex flex-grow space-x-2 overflow-hidden">
                      <div className="inline-flex items-center justify-center w-5 h-5 shrink-0 overflow-hidden rounded-full">
                        <CircleFlag
                          countryCode={option.alpha2.toLowerCase()}
                          height={20}
                        />
                      </div>
                      <span className="overflow-hidden text-ellipsis whitespace-nowrap">
                        {option.name}
                      </span>
                    </div>
                    <CheckIcon
                      className={cn(
                        "ml-auto h-4 w-4 shrink-0",
                        selectedCountry?.name === option.name
                          ? "opacity-100"
                          : "opacity-0"
                      )}
                    />
                  </CommandItem>
                ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

CountrySelectorComponent.displayName = "CountrySelector"

export const CountrySelector = forwardRef(CountrySelectorComponent)
