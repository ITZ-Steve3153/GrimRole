import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
from dotenv import load_dotenv
from keep_alive import keep_alive  # ✅ Import keep_alive

load_dotenv()  # Load .env file if present locally

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# In-memory config
trigger_roles = set()
removal_roles = set()
punishment_roles = {}
check_interval = 60  # seconds
punishment_check_interval = 60  # seconds

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user}")
    interval_check.start()
    punishment_check.start()

# === Slash Commands ===

@tree.command(name="add-trigger", description="Add a trigger role")
@app_commands.describe(role="The trigger role")
async def add_trigger(interaction: discord.Interaction, role: discord.Role):
    trigger_roles.add(role.id)
    await interaction.response.send_message(f"✅ Added {role.name} as a trigger role.")

@tree.command(name="remove-trigger", description="Remove a trigger role")
@app_commands.describe(role="The trigger role to remove")
async def remove_trigger(interaction: discord.Interaction, role: discord.Role):
    trigger_roles.discard(role.id)
    await interaction.response.send_message(f"❌ Removed {role.name} from trigger roles.")

@tree.command(name="add-remove-role", description="Add a role to be removed when trigger is added")
@app_commands.describe(role="The role to remove")
async def add_remove_role(interaction: discord.Interaction, role: discord.Role):
    removal_roles.add(role.id)
    await interaction.response.send_message(f"🔧 Added {role.name} to removal list.")

@tree.command(name="remove-remove-role", description="Remove a role from the removal list")
@app_commands.describe(role="The role to remove")
async def remove_remove_role(interaction: discord.Interaction, role: discord.Role):
    removal_roles.discard(role.id)
    await interaction.response.send_message(f"🗑️ Removed {role.name} from removal list.")

@tree.command(name="list-roles", description="List all trigger/removal roles")
async def list_roles(interaction: discord.Interaction):
    guild = interaction.guild
    trigger_list = [guild.get_role(r).mention for r in trigger_roles if guild.get_role(r)]
    removal_list = [guild.get_role(r).mention for r in removal_roles if guild.get_role(r)]
    await interaction.response.send_message(
        f"**Trigger Roles:** {', '.join(trigger_list) or 'None'}\n"
        f"**Roles to Remove:** {', '.join(removal_list) or 'None'}"
    )

@tree.command(name="set-check-interval", description="Set how often the bot checks roles (in seconds)")
@app_commands.describe(seconds="Check interval in seconds")
async def set_check_interval(interaction: discord.Interaction, seconds: int):
    global check_interval
    check_interval = seconds
    interval_check.change_interval(seconds=check_interval)
    await interaction.response.send_message(f"⏱️ Interval set to {seconds} seconds.")

# === Interval check ===

@tasks.loop(seconds=check_interval)
async def interval_check():
    for guild in bot.guilds:
        for member in guild.members:
            if any(role.id in trigger_roles for role in member.roles):
                for role_id in removal_roles:
                    role = guild.get_role(role_id)
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role, reason="Trigger role conflict")
                        except:
                            pass

# === Punishment Role System ===

@tree.command(name="add-punishment-role", description="Set a punishment for a role")
@app_commands.describe(role="Role to punish", action="mute/kick/ban", delay="Time in seconds")
async def add_punishment(interaction: discord.Interaction, role: discord.Role, action: str, delay: int):
    if action.lower() not in ["mute", "kick", "ban"]:
        await interaction.response.send_message("❌ Invalid action. Use mute, kick, or ban.")
        return
    punishment_roles[role.id] = {"action": action.lower(), "delay": delay, "applied": {}}
    await interaction.response.send_message(f"✅ Users with {role.name} will be {action}ed after {delay} seconds.")

@tree.command(name="remove-punishment-role", description="Remove punishment from a role")
@app_commands.describe(role="Role to stop punishing")
async def remove_punishment(interaction: discord.Interaction, role: discord.Role):
    if role.id in punishment_roles:
        del punishment_roles[role.id]
        await interaction.response.send_message(f"🛑 Removed punishment for {role.name}.")
    else:
        await interaction.response.send_message("Role not found in punishment list.")

@tasks.loop(seconds=punishment_check_interval)
async def punishment_check():
    for guild in bot.guilds:
        for member in guild.members:
            for role_id, info in punishment_roles.items():
                role = guild.get_role(role_id)
                if role and role in member.roles:
                    if member.id not in info["applied"]:
                        info["applied"][member.id] = asyncio.get_event_loop().time()
                    else:
                        elapsed = asyncio.get_event_loop().time() - info["applied"][member.id]
                        if elapsed >= info["delay"]:
                            try:
                                if info["action"] == "kick":
                                    await member.kick(reason="Punishment role triggered")
                                elif info["action"] == "ban":
                                    await member.ban(reason="Punishment role triggered")
                                elif info["action"] == "mute":
                                    await member.edit(roles=[r for r in member.roles if r.id != role.id])
                                del info["applied"][member.id]
                            except:
                                pass
                else:
                    if member.id in info["applied"]:
                        del info["applied"][member.id]

# === Immediate Role Check on Role Change ===

@bot.event
async def on_member_update(before, after):
    added_roles = set(after.roles) - set(before.roles)
    for role in added_roles:
        # Trigger role was added
        if role.id in trigger_roles:
            for rem_id in removal_roles:
                rem_role = after.guild.get_role(rem_id)
                if rem_role in after.roles:
                    try:
                        await after.remove_roles(rem_role, reason="Trigger role added")
                    except:
                        pass

        # Punishment role added
        if role.id in punishment_roles:
            punishment_roles[role.id]["applied"][after.id] = asyncio.get_event_loop().time()
            if punishment_roles[role.id]["delay"] == 0:
                try:
                    action = punishment_roles[role.id]["action"]
                    if action == "kick":
                        await after.kick(reason="Immediate punishment role triggered")
                    elif action == "ban":
                        await after.ban(reason="Immediate punishment role triggered")
                    elif action == "mute":
                        await after.edit(roles=[r for r in after.roles if r.id != role.id])
                except Exception as e:
                    print(f"Error during immediate punishment: {e}")

# === Start the Bot ===

keep_alive()  # ✅ Start the dummy web server for Render
bot.run(os.getenv("DISCORD_TOKEN"))
