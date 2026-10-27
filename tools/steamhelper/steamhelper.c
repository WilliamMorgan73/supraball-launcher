/*
 * Everything the launcher needs from Steam for Supraball, in one run, as JSON:
 * an Encrypted App Ticket (to sign in to the master server), the player's Steam ID, name and
 * country, their Steam Inventory items, and every item definition in the game.
 *
 * Runs under Proton with SteamAppId=321400 using the official launcher's 32-bit steam_api.dll,
 * which has Steam's flat C API.
 *
 * Usage: steamhelper.exe <path\to\steam_api.dll> <output file>
 * Exit codes: 0 ok, 2 bad args, 3 dll load, 4 SteamAPI_Init failed, 5 missing interface,
 *             6 ticket timed out, 7 inventory timed out, 8 can't write output.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

typedef struct {
    uint64_t item_id;
    int32_t definition;
    uint16_t quantity;
    uint16_t flags;
} SteamItemDetails;

#define RESULT_OK 1
#define RESULT_PENDING 22

typedef int (__cdecl *Init_t)(void);
typedef void (__cdecl *Void_t)(void);
typedef int32_t (__cdecl *Handle_t)(void);
typedef void *(__cdecl *SteamClient_t)(void);
typedef void *(__cdecl *GetUserIface_t)(void *client, int32_t user, int32_t pipe, const char *version);
typedef void *(__cdecl *GetPipeIface_t)(void *client, int32_t pipe, const char *version);
typedef uint64_t (__cdecl *RequestTicket_t)(void *user, void *data, int cb_data);
typedef int (__cdecl *GetTicket_t)(void *user, void *ticket, int cb_max, uint32_t *cb_ticket);
typedef uint64_t (__cdecl *GetSteamID_t)(void *user);
typedef const char *(__cdecl *GetString_t)(void *iface);
typedef int (__cdecl *GetAllItems_t)(void *inv, int32_t *result);
typedef int (__cdecl *GetResultStatus_t)(void *inv, int32_t result);
typedef int (__cdecl *GetResultItems_t)(void *inv, int32_t result, SteamItemDetails *items, uint32_t *count);
typedef void (__cdecl *DestroyResult_t)(void *inv, int32_t result);
typedef int (__cdecl *LoadDefs_t)(void *inv);
typedef int (__cdecl *GetDefIDs_t)(void *inv, int32_t *ids, uint32_t *count);
typedef int (__cdecl *GetDefProp_t)(void *inv, int32_t def, const char *name, char *buf, uint32_t *size);

static GetDefProp_t get_prop;
static void *inventory;

static void json_string(FILE *out, const char *s) {
    fputc('"', out);
    for (; s && *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') fprintf(out, "\\%c", c);
        else if (c < 0x20) fprintf(out, "\\u%04x", c);
        else fputc(c, out);
    }
    fputc('"', out);
}

static char *property(int32_t def, const char *name) {
    uint32_t size = 0;
    get_prop(inventory, def, name, NULL, &size);
    if (size == 0) return NULL;
    char *buf = calloc(size + 1, 1);
    if (!get_prop(inventory, def, name, buf, &size)) {
        free(buf);
        return NULL;
    }
    return buf;
}

static void write_def(FILE *out, int32_t def) {
    fprintf(out, "\"%d\":{", def);
    char *names = property(def, NULL); /* comma-separated list of property names */
    int first = 1;
    if (names) {
        for (char *name = strtok(names, ","); name; name = strtok(NULL, ",")) {
            char *value = property(def, name);
            if (!value) continue;
            if (!first) fputc(',', out);
            json_string(out, name);
            fputc(':', out);
            json_string(out, value);
            free(value);
            first = 0;
        }
        free(names);
    }
    fputc('}', out);
}

#define LOAD(var, type, name) type var = (type)GetProcAddress(dll, name); if (!var) return 3

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: steamhelper.exe <steam_api.dll> <output file>\n");
        return 2;
    }
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) return 3;
    LOAD(init, Init_t, "SteamAPI_Init");
    LOAD(run_callbacks, Void_t, "SteamAPI_RunCallbacks");
    LOAD(shutdown, Void_t, "SteamAPI_Shutdown");
    LOAD(get_huser, Handle_t, "SteamAPI_GetHSteamUser");
    LOAD(get_hpipe, Handle_t, "SteamAPI_GetHSteamPipe");
    LOAD(steam_client, SteamClient_t, "SteamClient");
    LOAD(get_user_iface, GetUserIface_t, "SteamAPI_ISteamClient_GetISteamUser");
    LOAD(get_friends_iface, GetUserIface_t, "SteamAPI_ISteamClient_GetISteamFriends");
    LOAD(get_inventory_iface, GetUserIface_t, "SteamAPI_ISteamClient_GetISteamInventory");
    LOAD(get_utils_iface, GetPipeIface_t, "SteamAPI_ISteamClient_GetISteamUtils");
    LOAD(request_ticket, RequestTicket_t, "SteamAPI_ISteamUser_RequestEncryptedAppTicket");
    LOAD(get_ticket, GetTicket_t, "SteamAPI_ISteamUser_GetEncryptedAppTicket");
    LOAD(get_steam_id, GetSteamID_t, "SteamAPI_ISteamUser_GetSteamID");
    LOAD(get_persona_name, GetString_t, "SteamAPI_ISteamFriends_GetPersonaName");
    LOAD(get_ip_country, GetString_t, "SteamAPI_ISteamUtils_GetIPCountry");
    LOAD(get_all, GetAllItems_t, "SteamAPI_ISteamInventory_GetAllItems");
    LOAD(get_status, GetResultStatus_t, "SteamAPI_ISteamInventory_GetResultStatus");
    LOAD(get_items, GetResultItems_t, "SteamAPI_ISteamInventory_GetResultItems");
    LOAD(destroy, DestroyResult_t, "SteamAPI_ISteamInventory_DestroyResult");
    LOAD(load_defs, LoadDefs_t, "SteamAPI_ISteamInventory_LoadItemDefinitions");
    LOAD(get_def_ids, GetDefIDs_t, "SteamAPI_ISteamInventory_GetItemDefinitionIDs");
    get_prop = (GetDefProp_t)GetProcAddress(dll, "SteamAPI_ISteamInventory_GetItemDefinitionProperty");
    if (!get_prop) return 3;

    if (!init()) return 4;
    void *client = steam_client();
    int32_t huser = get_huser(), hpipe = get_hpipe();
    void *user = get_user_iface(client, huser, hpipe, "SteamUser019");
    void *friends = get_friends_iface(client, huser, hpipe, "SteamFriends015");
    void *utils = get_utils_iface(client, hpipe, "SteamUtils008");
    inventory = get_inventory_iface(client, huser, hpipe, "STEAMINVENTORY_INTERFACE_V001");
    if (!user || !friends || !utils || !inventory) {
        shutdown();
        return 5;
    }

    request_ticket(user, NULL, 0);
    load_defs(inventory);
    int32_t result = -1;
    get_all(inventory, &result);

    unsigned char ticket[4096];
    uint32_t ticket_size = 0;
    uint32_t def_count = 0;
    int status = RESULT_PENDING;
    for (int i = 0; i < 300; i++) { /* ~15 s */
        run_callbacks();
        if (ticket_size == 0 && !get_ticket(user, ticket, sizeof ticket, &ticket_size)) ticket_size = 0;
        status = get_status(inventory, result);
        def_count = 0;
        get_def_ids(inventory, NULL, &def_count);
        if (ticket_size > 0 && status != RESULT_PENDING && def_count > 0) break;
        Sleep(50);
    }
    if (ticket_size == 0) {
        shutdown();
        return 6;
    }
    if (status != RESULT_OK || def_count == 0) {
        shutdown();
        return 7;
    }

    uint32_t item_count = 0;
    get_items(inventory, result, NULL, &item_count);
    SteamItemDetails *items = calloc(item_count ? item_count : 1, sizeof *items);
    get_items(inventory, result, items, &item_count);
    destroy(inventory, result);

    FILE *out = fopen(argv[2], "w");
    if (!out) {
        shutdown();
        return 8;
    }
    fprintf(out, "{\"steamid\":\"%llu\",\"name\":", (unsigned long long)get_steam_id(user));
    json_string(out, get_persona_name(friends));
    fputs(",\"country\":", out);
    json_string(out, get_ip_country(utils));
    fputs(",\"ticket\":\"", out);
    for (uint32_t j = 0; j < ticket_size; j++) fprintf(out, "%02x", ticket[j]);
    fputs("\",\"items\":[", out);
    for (uint32_t i = 0; i < item_count; i++)
        fprintf(out, "%s{\"id\":\"%llu\",\"def\":%d,\"quantity\":%u}", i ? "," : "",
                (unsigned long long)items[i].item_id, items[i].definition, items[i].quantity);
    /* Every definition, owned or not: the launcher's catalogue preview shows them all. */
    fputs("],\"defs\":{", out);
    int32_t *defs = calloc(def_count, sizeof *defs);
    get_def_ids(inventory, defs, &def_count);
    for (uint32_t i = 0; i < def_count; i++) {
        if (i) fputc(',', out);
        write_def(out, defs[i]);
    }
    fputs("}}\n", out);
    fclose(out);
    shutdown();
    return 0;
}
