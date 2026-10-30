/*
 * reenumerate <vendor-id> <product-id> [serial]
 *
 * Re-enumerates a USB device: macOS sees it unplugged and plugged back in, as
 * if you'd done it by hand. src/recover.ts runs it on a deck the Stream Deck
 * app has given up on. Needs no root. Exits 0 on success, 1 if there's no such
 * device (or the arguments are wrong), 2 if re-enumerating failed.
 */

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int serial_matches(io_service_t service, const char *serial) {
    if (!serial) return 1;
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, CFSTR(kUSBSerialNumberString), kCFAllocatorDefault, 0);
    char buffer[256] = "";
    if (value && CFGetTypeID(value) == CFStringGetTypeID()) {
        CFStringGetCString(value, buffer, sizeof buffer, kCFStringEncodingUTF8);
    }
    if (value) CFRelease(value);
    return strcmp(buffer, serial) == 0;
}

static IOReturn reenumerate(io_service_t service) {
    IOCFPlugInInterface **plugin = NULL;
    SInt32 score;
    kern_return_t kr = IOCreatePlugInInterfaceForService(service, kIOUSBDeviceUserClientTypeID,
                                                         kIOCFPlugInInterfaceID, &plugin, &score);
    if (kr != KERN_SUCCESS || !plugin) return kr ? kr : kIOReturnError;
    IOUSBDeviceInterface650 **device = NULL;
    (*plugin)->QueryInterface(plugin, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID650), (LPVOID *)&device);
    (*plugin)->Release(plugin);
    if (!device) return kIOReturnUnsupported;

    IOReturn opened = (*device)->USBDeviceOpen(device);
    IOReturn result = (*device)->USBDeviceReEnumerate(device, 0);
    if (opened == kIOReturnSuccess) (*device)->USBDeviceClose(device);
    (*device)->Release(device);
    return result;
}

int main(int argc, char **argv) {
    if (argc < 3 || argc > 4) {
        fprintf(stderr, "usage: %s <vendor-id> <product-id> [serial]\n", argv[0]);
        return 1;
    }
    int vendor = atoi(argv[1]), product = atoi(argv[2]);
    const char *serial = argc == 4 ? argv[3] : NULL;

    CFMutableDictionaryRef match = IOServiceMatching(kIOUSBDeviceClassName);
    CFNumberRef vendorRef = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &vendor);
    CFNumberRef productRef = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &product);
    CFDictionarySetValue(match, CFSTR(kUSBVendorID), vendorRef);
    CFDictionarySetValue(match, CFSTR(kUSBProductID), productRef);
    CFRelease(vendorRef);
    CFRelease(productRef);

    io_iterator_t iterator;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, match, &iterator) != KERN_SUCCESS) return 1;
    int found = 0;
    IOReturn result = kIOReturnSuccess;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        if (serial_matches(service, serial)) {
            found = 1;
            result = reenumerate(service);
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);

    if (!found) {
        fprintf(stderr, "no USB device %d:%d%s%s\n", vendor, product, serial ? " with serial " : "", serial ? serial : "");
        return 1;
    }
    if (result != kIOReturnSuccess) {
        fprintf(stderr, "re-enumerating failed: 0x%x\n", result);
        return 2;
    }
    return 0;
}
